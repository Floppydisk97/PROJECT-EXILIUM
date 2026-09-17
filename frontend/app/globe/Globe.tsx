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

const SEA = 0.995;      // smooth ocean shell
const CLOUDS = 1.062;   // cloud deck, just above the tallest land
const RIM = 1.085;      // atmospheric rim drawn over the planet's own limb
const HALO = 1.5;      // outer halo shell; its falloff ends well inside it
const HALO_EDGE = 1.26; // distance from planet centre where the halo fades to zero

function landRadius(elevation: number): number {
  return 1 + Math.min(Math.max(elevation, 0), 4500) / 4500 * 0.05;
}

// Shared GLSL: view-space position (and normal) for the atmosphere/cloud shells.
const VIEW_VERT = `
  varying vec3 vP; varying vec3 vN; varying vec3 vLocal;
  void main() {
    vLocal = position;
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vP = mv.xyz;
    gl_Position = projectionMatrix * mv;
  }`;

export default function Globe() {
  const mountRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [selected, setSelected] = useState<Tile | null>(null);
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
      scene.background = new THREE.Color(0x05070e);

      const camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 100);
      camera.position.set(0, 0.3, 3.2);

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
      renderer.setSize(width, height);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      mount.appendChild(renderer.domElement);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enablePan = false;
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.rotateSpeed = 0.5;
      controls.minDistance = 1.35;
      controls.maxDistance = 6;
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.32;
      controls.addEventListener("start", () => { controls.autoRotate = false; });

      // Bright, even illumination (like the reference globes) with just enough
      // directional shading to keep the sphere reading as a sphere.
      scene.add(new THREE.AmbientLight(0xffffff, 1.05));
      scene.add(new THREE.HemisphereLight(0xdcecff, 0x4a5a78, 0.45));
      const sun = new THREE.DirectionalLight(0xfff4e2, 0.55);
      sun.position.set(2.2, 1.5, 4);
      scene.add(sun);

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
      scene.add(stars(1300, 0x9db0d2, 0.11, 42));
      scene.add(stars(200, 0xffffff, 0.2, 46));

      scene.add(new THREE.Mesh(
        new THREE.SphereGeometry(0.95, 48, 48),
        new THREE.MeshBasicMaterial({ color: 0x24486b }),
      ));

      scene.add(new THREE.Mesh(
        new THREE.SphereGeometry(SEA, 128, 128),
        new THREE.MeshStandardMaterial({ color: 0x35688f, roughness: 0.6, metalness: 0.03 }),
      ));

      // Land hexes.
      const positions: number[] = [];
      const colors: number[] = [];
      const borders: number[] = [];
      const faceTile: number[] = [];
      const tilesById = new Map<number, Tile>();
      const tmp = new THREE.Color();

      for (const tile of map.tiles) {
        if (tile.elevation < 0) continue;
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
        new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.92, metalness: 0.0 }),
      );
      scene.add(land);

      const borderGeom = new THREE.BufferGeometry();
      borderGeom.setAttribute("position", new THREE.Float32BufferAttribute(borders, 3));
      scene.add(new THREE.LineSegments(
        borderGeom,
        new THREE.LineBasicMaterial({ color: 0x14301f, transparent: true, opacity: 0.20 }),
      ));

      // Drifting procedural cloud deck.
      const cloudMat = new THREE.ShaderMaterial({
        uniforms: {
          uTime: { value: 0 },
          uSun: { value: new THREE.Vector3(0, 0, 1) },
          uOpacity: { value: 0.42 },
        },
        vertexShader: VIEW_VERT,
        fragmentShader: `
          varying vec3 vP; varying vec3 vN; varying vec3 vLocal;
          uniform float uTime; uniform vec3 uSun; uniform float uOpacity;
          float hash(vec3 p){ return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
          float noise(vec3 p){
            vec3 i = floor(p); vec3 f = fract(p); f = f * f * (3.0 - 2.0 * f);
            return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x),
                           mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
                       mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
                           mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
          }
          float fbm(vec3 p){
            float v = 0.0, a = 0.5;
            for (int i = 0; i < 4; i++) { v += a * noise(p); p *= 2.03; a *= 0.5; }
            return v;
          }
          void main(){
            vec3 p = vLocal * 2.4 + vec3(uTime * 0.012, uTime * 0.006, 0.0);
            float n = fbm(p);
            float a = smoothstep(0.48, 0.70, n);
            if (a < 0.004) discard;
            float lambert = clamp(dot(normalize(vN), normalize(uSun)), 0.0, 1.0);
            float shade = 0.62 + 0.38 * lambert;
            gl_FragColor = vec4(vec3(shade), a * uOpacity);
          }`,
        transparent: true,
        depthWrite: false,
      });
      const clouds = new THREE.Mesh(new THREE.SphereGeometry(CLOUDS, 72, 72), cloudMat);
      scene.add(clouds);

      // Atmospheric rim over the planet's own limb (kills the hard inner edge).
      const rimMat = new THREE.ShaderMaterial({
        uniforms: { uColor: { value: new THREE.Color(0x9fd2ff) }, uPower: { value: 3.4 }, uStrength: { value: 0.16 } },
        vertexShader: VIEW_VERT,
        fragmentShader: `
          varying vec3 vP; varying vec3 vN; varying vec3 vLocal;
          uniform vec3 uColor; uniform float uPower; uniform float uStrength;
          void main(){
            float f = pow(clamp(1.0 - dot(vN, normalize(-vP)), 0.0, 1.0), uPower);
            gl_FragColor = vec4(uColor, f * uStrength);
          }`,
        side: THREE.FrontSide, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false,
      });
      scene.add(new THREE.Mesh(new THREE.SphereGeometry(RIM, 64, 64), rimMat));

      // Outer halo: alpha from the ray's distance to the planet centre, so it is a
      // smooth gradient hugging the planet instead of a hard-edged ring.
      const haloMat = new THREE.ShaderMaterial({
        uniforms: {
          uCenter: { value: new THREE.Vector3() },
          uInner: { value: 1.02 },
          uOuter: { value: HALO_EDGE },
          uColor: { value: new THREE.Color(0x6fb4ff) },
          uStrength: { value: 0.16 },
        },
        vertexShader: VIEW_VERT,
        fragmentShader: `
          varying vec3 vP; varying vec3 vN; varying vec3 vLocal;
          uniform vec3 uCenter; uniform float uInner; uniform float uOuter;
          uniform vec3 uColor; uniform float uStrength;
          void main(){
            vec3 dir = normalize(vP);
            float t = max(dot(uCenter, dir), 0.0);
            float d = length(uCenter - t * dir);
            float f = 1.0 - smoothstep(uInner, uOuter, d);
            f = pow(f, 2.0);
            gl_FragColor = vec4(uColor, f * uStrength);
          }`,
        side: THREE.BackSide, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false,
      });
      const halo = new THREE.Mesh(new THREE.SphereGeometry(HALO, 64, 64), haloMat);
      scene.add(halo);

      const composer = new EffectComposer(renderer);
      composer.addPass(new RenderPass(scene, camera));
      composer.addPass(new UnrealBloomPass(new THREE.Vector2(width, height), 0.18, 0.5, 0.88));
      composer.addPass(new OutputPass());
      composer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
      composer.setSize(width, height);

      let highlight: THREE.LineLoop | null = null;
      highlightRef.current = (tile: Tile | null) => {
        if (highlight) { scene.remove(highlight); highlight.geometry.dispose(); highlight = null; }
        if (!tile || tile.elevation < 0) return;
        const r = landRadius(tile.elevation) * 1.004;
        const pts = tile.polygon.map((p) => new THREE.Vector3(p[0] * r, p[1] * r, p[2] * r));
        highlight = new THREE.LineLoop(
          new THREE.BufferGeometry().setFromPoints(pts),
          new THREE.LineBasicMaterial({ color: 0xffd34d }),
        );
        scene.add(highlight);
      };

      const raycaster = new THREE.Raycaster();
      const pointer = new THREE.Vector2();
      const downAt = new THREE.Vector2();
      const onPointerDown = (e: PointerEvent) => { downAt.set(e.clientX, e.clientY); };
      const onPointerUp = (e: PointerEvent) => {
        if (downAt.distanceTo(new THREE.Vector2(e.clientX, e.clientY)) > 6) return;
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

      const sunView = new THREE.Vector3();
      const clock = new THREE.Clock();
      let raf = 0;
      const animate = () => {
        raf = requestAnimationFrame(animate);
        const t = clock.getElapsedTime();
        controls.update();
        clouds.rotation.y += 0.00022;
        cloudMat.uniforms.uTime.value = t;
        sunView.copy(sun.position).normalize().transformDirection(camera.matrixWorldInverse);
        cloudMat.uniforms.uSun.value.copy(sunView);
        haloMat.uniforms.uCenter.value.set(0, 0, 0).applyMatrix4(camera.matrixWorldInverse);
        halo.visible = camera.position.length() > HALO_EDGE + 0.15; // hide once "inside" the air
        composer.render();
      };
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
