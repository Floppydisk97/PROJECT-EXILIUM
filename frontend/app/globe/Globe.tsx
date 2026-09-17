"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { biomeColor, biomeLabel, type Tile, type WorldMap } from "./biomes";

type Status = "loading" | "ready" | "ungenerated" | "error";

const SEA = 0.995; // smooth ocean shell radius; land rises above it.

// Land relief: hexes bulge outward with elevation so continents read as 3D from orbit.
function landRadius(elevation: number): number {
  return 1 + Math.min(Math.max(elevation, 0), 4500) / 4500 * 0.05;
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
        const res = await fetch("/api/map", { signal: AbortSignal.timeout(30000) });
        if (res.status === 404) { if (!disposed) setStatus("ungenerated"); return; }
        if (!res.ok) { if (!disposed) setStatus("error"); return; }
        map = (await res.json()) as WorldMap;
      } catch {
        if (!disposed) setStatus("error");
        return;
      }
      if (disposed || !mountRef.current) return;

      const mount = mountRef.current;
      let width = mount.clientWidth;
      let height = mount.clientHeight;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x04060b);

      const camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 100);
      camera.position.set(0, 0.3, 3.2);

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height);
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.15;
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      mount.appendChild(renderer.domElement);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enablePan = false;
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.rotateSpeed = 0.5;
      controls.minDistance = 1.4;
      controls.maxDistance = 6;
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.32;
      controls.addEventListener("start", () => { controls.autoRotate = false; }); // idle spin until touched

      // Lighting: one strong warm sun casts a real day/night terminator; a faint cool
      // fill keeps the night side from going pure black (earthshine).
      scene.add(new THREE.AmbientLight(0xffffff, 0.62));
      const sun = new THREE.DirectionalLight(0xfff2dc, 1.35);
      sun.position.set(1.5, 1.6, 5); // sun-ward face (toward camera) stays bright
      scene.add(sun);
      const fill = new THREE.DirectionalLight(0x2b4a78, 0.3);
      fill.position.set(-4, -1, -3);
      scene.add(fill);

      // Starfield: many faint stars plus a sprinkle of bright ones.
      const stars = (count: number, color: number, size: number, near: number) => {
        const g = new THREE.BufferGeometry();
        const p = new Float32Array(count * 3);
        for (let i = 0; i < count; i++) {
          const v = new THREE.Vector3().randomDirection().multiplyScalar(near + Math.random() * 25);
          p.set([v.x, v.y, v.z], i * 3);
        }
        g.setAttribute("position", new THREE.BufferAttribute(p, 3));
        return new THREE.Points(g, new THREE.PointsMaterial({ color, size, sizeAttenuation: true }));
      };
      scene.add(stars(1300, 0x8ea2c6, 0.11, 42));
      scene.add(stars(180, 0xffffff, 0.2, 46));

      // Deep base sphere behind everything: fills any hairline gap with dark water.
      scene.add(new THREE.Mesh(
        new THREE.SphereGeometry(0.95, 48, 48),
        new THREE.MeshBasicMaterial({ color: 0x081120 }),
      ));

      // Smooth glossy ocean shell — catches a sun glint like real water.
      scene.add(new THREE.Mesh(
        new THREE.SphereGeometry(SEA, 128, 128),
        new THREE.MeshStandardMaterial({ color: 0x1d4b7e, roughness: 0.52, metalness: 0.05 }),
      ));

      // Land as raised biome-coloured hexes (matte). faceTile maps a picked face to its tile.
      const positions: number[] = [];
      const colors: number[] = [];
      const borders: number[] = [];
      const faceTile: number[] = [];
      const tilesById = new Map<number, Tile>();
      const tmp = new THREE.Color();

      for (const tile of map.tiles) {
        if (tile.elevation < 0) continue; // oceans are the smooth shell, not hexes
        tilesById.set(tile.id, tile);
        const r = landRadius(tile.elevation);
        const c = tile.center;
        tmp.setHex(biomeColor(tile.biome)).convertSRGBToLinear();
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
      const land = new THREE.Mesh(
        geom,
        new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, metalness: 0.02 }),
      );
      scene.add(land);

      const borderGeom = new THREE.BufferGeometry();
      borderGeom.setAttribute("position", new THREE.Float32BufferAttribute(borders, 3));
      scene.add(new THREE.LineSegments(
        borderGeom,
        new THREE.LineBasicMaterial({ color: 0x0a1a10, transparent: true, opacity: 0.15 }),
      ));

      // Atmosphere: a back-facing shell whose rim glows via a Fresnel term.
      const atmosphere = new THREE.Mesh(
        new THREE.SphereGeometry(1.075, 64, 64),
        new THREE.ShaderMaterial({
          uniforms: { glowColor: { value: new THREE.Color(0x2b62b4) }, power: { value: 3.0 } },
          vertexShader: `
            varying vec3 vN; varying vec3 vP;
            void main(){ vN = normalize(normalMatrix * normal);
              vP = (modelViewMatrix * vec4(position,1.0)).xyz;
              gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
          fragmentShader: `
            varying vec3 vN; varying vec3 vP; uniform vec3 glowColor; uniform float power;
            void main(){ float f = pow(clamp(1.0 - dot(vN, normalize(-vP)), 0.0, 1.0), power);
              gl_FragColor = vec4(glowColor, f * 0.4); }`,
          side: THREE.BackSide, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false,
        }),
      );
      scene.add(atmosphere);

      // Post-processing: subtle bloom so the atmosphere, ocean glint and ice glow.
      const composer = new EffectComposer(renderer);
      composer.addPass(new RenderPass(scene, camera));
      const bloom = new UnrealBloomPass(new THREE.Vector2(width, height), 0.16, 0.4, 0.92);
      composer.addPass(bloom);
      composer.addPass(new OutputPass());
      composer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      composer.setSize(width, height);

      // Bright outline for the selected tile, rebuilt on each selection.
      let highlight: THREE.LineLoop | null = null;
      highlightRef.current = (tile: Tile | null) => {
        if (highlight) { scene.remove(highlight); highlight.geometry.dispose(); highlight = null; }
        if (!tile || tile.elevation < 0) return;
        const r = landRadius(tile.elevation) * 1.004;
        const pts = tile.polygon.map((p) => new THREE.Vector3(p[0] * r, p[1] * r, p[2] * r));
        const hg = new THREE.BufferGeometry().setFromPoints(pts);
        highlight = new THREE.LineLoop(hg, new THREE.LineBasicMaterial({ color: 0xffd34d }));
        scene.add(highlight);
      };

      // Picking (land tiles only; the ocean is a smooth shell).
      const raycaster = new THREE.Raycaster();
      const pointer = new THREE.Vector2();
      const downAt = new THREE.Vector2();
      const onPointerDown = (e: PointerEvent) => { downAt.set(e.clientX, e.clientY); };
      const onPointerUp = (e: PointerEvent) => {
        if (downAt.distanceTo(new THREE.Vector2(e.clientX, e.clientY)) > 6) return; // a drag
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObject(land)[0];
        if (hit && hit.faceIndex != null) {
          const tile = tilesById.get(faceTile[hit.faceIndex]) ?? null;
          setSelected(tile);
          highlightRef.current?.(tile);
        }
      };
      renderer.domElement.addEventListener("pointerdown", onPointerDown);
      renderer.domElement.addEventListener("pointerup", onPointerUp);

      const onResize = () => {
        width = mount.clientWidth; height = mount.clientHeight;
        camera.aspect = width / height; camera.updateProjectionMatrix();
        renderer.setSize(width, height);
        composer.setSize(width, height);
      };
      const resizeObserver = new ResizeObserver(onResize);
      resizeObserver.observe(mount);

      let raf = 0;
      const animate = () => { raf = requestAnimationFrame(animate); controls.update(); composer.render(); };
      animate();
      if (!disposed) setStatus("ready");

      controllers.push({ dispose: () => {
        cancelAnimationFrame(raf);
        resizeObserver.disconnect();
        renderer.domElement.removeEventListener("pointerdown", onPointerDown);
        renderer.domElement.removeEventListener("pointerup", onPointerUp);
        controls.dispose();
        composer.dispose();
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
          {status === "ungenerated" && <p>Il mondo non è ancora stato generato.</p>}
          {status === "error" && <p>Server temporaneamente non disponibile.</p>}
        </div>
      )}

      {status === "ready" && !selected && (
        <p className="globe-hint">Trascina per ruotare · rotellina per zoomare · clicca una terra</p>
      )}
    </div>
  );
}
