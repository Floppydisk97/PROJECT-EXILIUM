"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { biomeColor, biomeLabel, type Tile, type WorldMap } from "./biomes";

type Status = "loading" | "ready" | "ungenerated" | "error";

// Subtle relief: land bulges out, ocean basins sink in, so the planet reads as 3D.
function tileRadius(t: Tile): number {
  if (t.elevation >= 0) return 1 + Math.min(t.elevation, 4500) / 4500 * 0.05;
  return 1 - Math.min(-t.elevation, 6000) / 6000 * 0.02;
}

export default function Globe() {
  const mountRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [selected, setSelected] = useState<Tile | null>(null);

  // Scene handles the picking highlight; React owns the info panel. They meet through refs.
  const highlightRef = useRef<((tile: Tile | null) => void) | null>(null);

  useEffect(() => {
    let disposed = false;
    const controllers: { dispose: () => void }[] = [];

    (async () => {
      let map: WorldMap;
      try {
        const res = await fetch("/api/map", { signal: AbortSignal.timeout(20000) });
        if (res.status === 404) { if (!disposed) setStatus("ungenerated"); return; }
        if (!res.ok) { if (!disposed) setStatus("error"); return; }
        map = (await res.json()) as WorldMap;
      } catch {
        if (!disposed) setStatus("error");
        return;
      }
      if (disposed || !mountRef.current) return;

      const mount = mountRef.current;
      const width = mount.clientWidth;
      const height = mount.clientHeight;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x05070d);

      const camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 100);
      camera.position.set(0, 0.25, 3.15);

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height);
      mount.appendChild(renderer.domElement);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enablePan = false;
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.rotateSpeed = 0.5;
      controls.minDistance = 1.35;
      controls.maxDistance = 6;
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.35;
      controls.addEventListener("start", () => { controls.autoRotate = false; }); // idle spin until touched

      scene.add(new THREE.AmbientLight(0xffffff, 0.75));
      const sun = new THREE.DirectionalLight(0xfff4e0, 1.1);
      sun.position.set(5, 3, 5);
      scene.add(sun);

      // Starfield backdrop for the "planet from space" look.
      const starGeom = new THREE.BufferGeometry();
      const starCount = 1400;
      const starPos = new Float32Array(starCount * 3);
      for (let i = 0; i < starCount; i++) {
        const v = new THREE.Vector3().randomDirection().multiplyScalar(40 + Math.random() * 20);
        starPos.set([v.x, v.y, v.z], i * 3);
      }
      starGeom.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
      scene.add(new THREE.Points(starGeom, new THREE.PointsMaterial({ color: 0x8899bb, size: 0.15, sizeAttenuation: true })));

      // Dark base sphere hides hairline cracks between tiles of differing elevation.
      scene.add(new THREE.Mesh(
        new THREE.SphereGeometry(0.965, 48, 48),
        new THREE.MeshBasicMaterial({ color: 0x0a1420 }),
      ));

      // One merged mesh (fast) with per-vertex biome colours; faceTile maps a picked
      // face back to its tile. Border segments give the hexagonal RimWorld outline.
      const positions: number[] = [];
      const colors: number[] = [];
      const faceTile: number[] = [];
      const borders: number[] = [];
      const tilesById = new Map<number, Tile>();
      const tmp = new THREE.Color();

      for (const tile of map.tiles) {
        tilesById.set(tile.id, tile);
        const r = tileRadius(tile);
        const c = tile.center;
        tmp.setHex(biomeColor(tile.biome));
        const ring = tile.polygon;
        for (let i = 0; i < ring.length; i++) {
          const a = ring[i];
          const b = ring[(i + 1) % ring.length];
          positions.push(c[0] * r, c[1] * r, c[2] * r);
          positions.push(a[0] * r, a[1] * r, a[2] * r);
          positions.push(b[0] * r, b[1] * r, b[2] * r);
          for (let k = 0; k < 3; k++) colors.push(tmp.r, tmp.g, tmp.b);
          faceTile.push(tile.id);
          borders.push(a[0] * r, a[1] * r, a[2] * r, b[0] * r, b[1] * r, b[2] * r);
        }
      }

      const geom = new THREE.BufferGeometry();
      geom.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      geom.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      geom.computeVertexNormals();
      const planet = new THREE.Mesh(
        geom,
        new THREE.MeshLambertMaterial({ vertexColors: true }),
      );
      scene.add(planet);

      const borderGeom = new THREE.BufferGeometry();
      borderGeom.setAttribute("position", new THREE.Float32BufferAttribute(borders, 3));
      scene.add(new THREE.LineSegments(
        borderGeom,
        new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.28 }),
      ));

      // Bright outline for the selected tile, rebuilt on each selection.
      let highlight: THREE.LineLoop | null = null;
      highlightRef.current = (tile: Tile | null) => {
        if (highlight) { scene.remove(highlight); highlight.geometry.dispose(); highlight = null; }
        if (!tile) return;
        const r = tileRadius(tile) * 1.002;
        const pts = tile.polygon.map((p) => new THREE.Vector3(p[0] * r, p[1] * r, p[2] * r));
        const hg = new THREE.BufferGeometry().setFromPoints(pts);
        highlight = new THREE.LineLoop(hg, new THREE.LineBasicMaterial({ color: 0xffd34d }));
        scene.add(highlight);
      };

      // Picking.
      const raycaster = new THREE.Raycaster();
      const pointer = new THREE.Vector2();
      const down = new THREE.Vector2();
      const onPointerDown = (e: PointerEvent) => { down.set(e.clientX, e.clientY); };
      const onPointerUp = (e: PointerEvent) => {
        if (down.distanceTo(new THREE.Vector2(e.clientX, e.clientY)) > 6) return; // a drag, not a click
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObject(planet)[0];
        if (hit && hit.faceIndex != null) {
          const tile = tilesById.get(faceTile[hit.faceIndex]) ?? null;
          setSelected(tile);
          highlightRef.current?.(tile);
        }
      };
      renderer.domElement.addEventListener("pointerdown", onPointerDown);
      renderer.domElement.addEventListener("pointerup", onPointerUp);

      const onResize = () => {
        const w = mount.clientWidth, h = mount.clientHeight;
        camera.aspect = w / h; camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      };
      const resizeObserver = new ResizeObserver(onResize);
      resizeObserver.observe(mount);

      let raf = 0;
      const animate = () => { raf = requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); };
      animate();
      if (!disposed) setStatus("ready");

      controllers.push({ dispose: () => {
        cancelAnimationFrame(raf);
        resizeObserver.disconnect();
        renderer.domElement.removeEventListener("pointerdown", onPointerDown);
        renderer.domElement.removeEventListener("pointerup", onPointerUp);
        controls.dispose();
        renderer.dispose();
        geom.dispose();
        borderGeom.dispose();
        if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      } });
    })();

    return () => { disposed = true; controllers.forEach((c) => c.dispose()); highlightRef.current = null; };
  }, []);

  return (
    <div className="globe-root">
      <div ref={mountRef} className="globe-canvas" />
      <h1 className="globe-title">Hesperia · Seleziona il sito di atterraggio</h1>

      {selected && (
        <aside className="globe-panel" role="status">
          <div className="globe-panel-head">
            <strong>{biomeLabel(selected.biome)}</strong>
            <button aria-label="Chiudi" onClick={() => { setSelected(null); highlightRef.current?.(null); }}>×</button>
          </div>
          <dl>
            <dt>Coordinate</dt><dd>{selected.lat.toFixed(2)}°, {selected.lon.toFixed(2)}°</dd>
            <dt>Temperatura media</dt><dd>{selected.temperature.toFixed(1)} °C</dd>
            <dt>Precipitazioni</dt><dd>{selected.rainfall} mm</dd>
            <dt>Elevazione</dt><dd>{selected.elevation} m</dd>
            <dt>Confini</dt><dd>{selected.neighbors.length} tile</dd>
          </dl>
        </aside>
      )}

      {status !== "ready" && (
        <div className="globe-overlay" role="status">
          {status === "loading" && <p>Caricamento del pianeta…</p>}
          {status === "ungenerated" && <p>Il mondo non è ancora stato generato.<br /><code>docker compose exec api python -m app.mapcli &quot;Hesperia-01&quot;</code></p>}
          {status === "error" && <p>Server temporaneamente non disponibile.</p>}
        </div>
      )}

      {status === "ready" && !selected && (
        <p className="globe-hint">Trascina per ruotare · rotellina per zoomare · clicca un tile</p>
      )}
    </div>
  );
}
