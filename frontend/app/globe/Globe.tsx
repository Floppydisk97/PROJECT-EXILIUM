"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import {
  biomeColor, biomeLabel, landmassLabel, WATER_BIOMES, type Tile, type WorldMap,
} from "./biomes";

type Status = "loading" | "ready" | "ungenerated" | "error";

const SEA = 0.995;      // smooth ocean shell
const ICE = 0.9975;     // sea ice floats just above the ocean shell
const CLOUDS = 1.082;   // cloud deck, just above the tallest peaks
const RIM = 1.11;       // atmospheric rim drawn over the planet's own limb
const HALO = 1.5;       // outer halo shell; its falloff ends well inside it
const HALO_EDGE = 1.3;  // distance from planet centre where the halo fades to zero
const NORMAL_BLEND = 0.62; // how far terrain normals lean off radial when shading relief
// Terrain is hillshaded by hand against this fixed direction in planet space instead of
// being lit by the scene: a map should stay readable everywhere, so the darkest slope is
// still bright and the limb never falls into shadow. Only the sea uses the scene lights.
const TERRAIN_LIGHT = new THREE.Vector3(0.52, -0.55, 0.65).normalize();
const SHADE_FLOOR = 0.80;   // brightness of a slope facing fully away from the light
const SHADE_RANGE = 0.34;   // extra brightness a slope facing straight into it picks up
const ALTITUDE_TINT = 0.24; // how much brighter the highest ground is than the lowest

// The planet's north pole is +Z, so the camera's up axis is +Z and the default view sits
// over the equator: north ends up at the top of the screen, like a globe on a stand.
const HOME_POSITION = new THREE.Vector3(1.9, -2.2, 0.95);
const UP = new THREE.Vector3(0, 0, 1);

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

// Deterministic per-tile jitter: breaks the flatness of a thousand identical hexes without
// inventing geography. Same id always gets the same shade.
function tileJitter(id: number): number {
  const x = Math.sin(id * 127.1) * 43758.5453;
  return (x - Math.floor(x) - 0.5) * 0.09;
}

export default function Globe() {
  const mountRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [selected, setSelected] = useState<Tile | null>(null);
  const highlightRef = useRef<((tile: Tile | null) => void) | null>(null);
  const resetViewRef = useRef<(() => void) | null>(null);

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

      // Relief exaggeration comes from the server together with the terrain normals it
      // computed against it, so geometry and shading can never drift apart.
      const relief = (elevation: number) =>
        1 + Math.min(Math.max(elevation, 0), map.elevation_max) / map.elevation_max * map.relief_gain;
      const tileRadius = (t: { elevation: number }) =>
        t.elevation >= 0 ? relief(t.elevation) : ICE;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x05070e);

      const camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 100);
      camera.up.copy(UP);
      camera.position.copy(HOME_POSITION);

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

      // Bright overall, but with a real key light: without it the mountain normals the
      // server ships would have nothing to catch and the relief would stay invisible.
      // The key sits just off the home camera's shoulder so the hemisphere the viewer
      // actually looks at is the lit one, and a soft fill keeps the limb from going black.
      // These light the ocean shell (and give the clouds their sun direction); the terrain
      // carries its own baked shading.
      scene.add(new THREE.AmbientLight(0xffffff, 1.0));
      scene.add(new THREE.HemisphereLight(0xdcecff, 0x66748f, 0.42));
      const sun = new THREE.DirectionalLight(0xfff4e2, 0.6);
      sun.position.copy(TERRAIN_LIGHT).multiplyScalar(5);
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

      // Terrain: land hexes plus the sea ice that forms the polar caps.
      const positions: number[] = [];
      const normals: number[] = [];
      const colors: number[] = [];
      const borders: number[] = [];
      const faceTile: number[] = [];
      const tilesById = new Map<number, Tile>();
      const tmp = new THREE.Color();
      const shadeNormal = new THREE.Vector3();

      for (const tile of map.tiles) {
        tilesById.set(tile.id, tile);
        const r = tileRadius(tile);
        const c = tile.center;
        // Leaning the terrain normal part-way back towards the radial one keeps ranges
        // catching the light without throwing every slope behind them into pitch black.
        const n = shadeNormal
          .set(
            c[0] + (tile.normal[0] - c[0]) * NORMAL_BLEND,
            c[1] + (tile.normal[1] - c[1]) * NORMAL_BLEND,
            c[2] + (tile.normal[2] - c[2]) * NORMAL_BLEND,
          )
          .normalize();
        const water = WATER_BIOMES.has(tile.biome);
        // Height brightens the ground on top of the hillshade, so a highland reads as a
        // highland even where it happens to face away from the light.
        const altitude = Math.min(Math.max(tile.elevation, 0), map.elevation_max) / map.elevation_max;
        const shade = (SHADE_FLOOR + SHADE_RANGE * Math.max(0, n.dot(TERRAIN_LIGHT)))
          * (1 + ALTITUDE_TINT * altitude)
          * (1 + tileJitter(tile.id));
        tmp.setHex(biomeColor(tile.biome)).convertSRGBToLinear().multiplyScalar(shade);
        const ring = tile.polygon;
        for (let i = 0; i < ring.length; i++) {
          const a = ring[i];
          const b = ring[(i + 1) % ring.length];
          positions.push(c[0] * r, c[1] * r, c[2] * r);
          positions.push(a[0] * r, a[1] * r, a[2] * r);
          positions.push(b[0] * r, b[1] * r, b[2] * r);
          // One terrain normal per tile: flat-shaded hexes whose facing follows the real
          // slope, which is what makes ranges catch the light and valleys fall into shadow.
          for (let k = 0; k < 3; k++) normals.push(n.x, n.y, n.z);
          for (let k = 0; k < 3; k++) colors.push(tmp.r, tmp.g, tmp.b);
          faceTile.push(tile.id);
          // Water has no parcels to outline; a grid over the ice caps just reads as an artefact.
          if (!water) borders.push(a[0] * r, a[1] * r, a[2] * r, b[0] * r, b[1] * r, b[2] * r);
        }
      }

      const geom = new THREE.BufferGeometry();
      geom.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      geom.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
      geom.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      // Unlit: the shading is already in the vertex colours, which is what keeps the map
      // evenly readable instead of half-lost on the night side of a physical light.
      const land = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ vertexColors: true }));
      scene.add(land);

      const borderGeom = new THREE.BufferGeometry();
      borderGeom.setAttribute("position", new THREE.Float32BufferAttribute(borders, 3));
      scene.add(new THREE.LineSegments(
        borderGeom,
        new THREE.LineBasicMaterial({ color: 0x14301f, transparent: true, opacity: 0.11 }),
      ));

      // Rivers: the backend already paired each reach with the tile it drains into, so this
      // is a plain segment list. Major rivers are drawn brighter than their headwaters.
      const riverGeoms: THREE.BufferGeometry[] = [];
      const reaches: Record<"minor" | "major", number[]> = { minor: [], major: [] };
      for (const r of map.rivers) {
        const ra = relief(r.ae) * 1.0015;
        const rb = relief(r.be) * 1.0015;
        const into = r.flow >= 70 ? reaches.major : reaches.minor;
        into.push(r.a[0] * ra, r.a[1] * ra, r.a[2] * ra, r.b[0] * rb, r.b[1] * rb, r.b[2] * rb);
      }
      for (const [kind, points] of Object.entries(reaches)) {
        if (!points.length) continue;
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
        riverGeoms.push(g);
        scene.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({
          color: kind === "major" ? 0x59b4e8 : 0x4e9ed0,
          transparent: true,
          opacity: kind === "major" ? 0.9 : 0.6,
        })));
      }

      // Drifting procedural cloud deck.
      const cloudMat = new THREE.ShaderMaterial({
        uniforms: {
          uTime: { value: 0 },
          uSun: { value: new THREE.Vector3(0, 0, 1) },
          uOpacity: { value: 0.62 },
        },
        vertexShader: VIEW_VERT,
        fragmentShader: `
          varying vec3 vP; varying vec3 vN; varying vec3 vLocal;
          uniform float uTime; uniform vec3 uSun; uniform float uOpacity;
          // Cheap integer-ish hash (no sin): cleaner and faster than the classic sin-hash.
          float hash(vec3 p){
            p = fract(p * 0.3183099 + vec3(0.11, 0.17, 0.13));
            p *= 17.0;
            return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
          }
          float noise(vec3 x){
            vec3 i = floor(x); vec3 f = fract(x); f = f * f * (3.0 - 2.0 * f);
            return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x),
                           mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
                       mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
                           mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
          }
          float fbm(vec3 p){
            float v = 0.0, a = 0.5;
            for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.07 + vec3(1.7, 9.2, 3.1); a *= 0.5; }
            return v;
          }
          void main(){
            vec3 p = vLocal * 3.0;
            float drift = uTime * 0.01;
            // One domain-warp step: bends the noise into the swirled bands of real weather
            // instead of the round blobs plain fbm gives.
            float w = fbm(p * 0.75 + vec3(drift, 0.0, -drift));
            float n = fbm(p + vec3(w * 1.5) + vec3(drift * 1.7, 0.0, 0.0));
            float cover = smoothstep(0.57, 0.77, n);
            if (cover < 0.004) discard;
            // Thicker cores, feathered edges.
            float a = cover * cover * (0.45 + 0.55 * w);
            float lambert = clamp(dot(normalize(vN), normalize(uSun)), 0.0, 1.0);
            vec3 col = mix(vec3(0.72, 0.77, 0.88), vec3(1.0), lambert);
            gl_FragColor = vec4(col, clamp(a, 0.0, 1.0) * uOpacity);
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
          uInner: { value: 1.04 },
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
        if (!tile) return;
        const r = tileRadius(tile) * 1.004;
        const pts = tile.polygon.map((p) => new THREE.Vector3(p[0] * r, p[1] * r, p[2] * r));
        highlight = new THREE.LineLoop(
          new THREE.BufferGeometry().setFromPoints(pts),
          new THREE.LineBasicMaterial({ color: 0xffd34d }),
        );
        scene.add(highlight);
      };

      // Flying the camera home rather than snapping there keeps the viewer oriented.
      let flight: { from: THREE.Vector3; started: number } | null = null;
      resetViewRef.current = () => {
        flight = { from: camera.position.clone(), started: performance.now() };
        controls.autoRotate = true;
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
        if (flight) {
          const k = Math.min(1, (performance.now() - flight.started) / 650);
          const ease = k * k * (3 - 2 * k);
          camera.position.lerpVectors(flight.from, HOME_POSITION, ease);
          camera.up.copy(UP);
          controls.target.set(0, 0, 0);
          if (k >= 1) flight = null;
        }
        controls.update();
        clouds.rotation.z += 0.00022;
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
        riverGeoms.forEach((g) => g.dispose());
        if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      } });
    })();

    return () => {
      disposed = true;
      controllers.forEach((c) => c.dispose());
      highlightRef.current = null;
      resetViewRef.current = null;
    };
  }, []);

  const water = selected ? WATER_BIOMES.has(selected.biome) : false;

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
            <dt>Quota</dt>
            <dd>{selected.elevation >= 0 ? `${selected.elevation} m` : `${-selected.elevation} m sotto il mare`}</dd>
            {selected.river_flow > 0 && (<><dt>Corso d&apos;acqua</dt><dd>portata {selected.river_flow}</dd></>)}
            <dt>Terra emersa</dt><dd>{water && selected.elevation < 0 ? "—" : landmassLabel(selected.landmass_size)}</dd>
            <dt>Confini</dt><dd>{selected.neighbor_count} tile</dd>
          </dl>
          {water && <p className="globe-panel-note">Acqua: nessuna colonia può insediarsi qui.</p>}
        </aside>
      )}

      {status === "ready" && (
        <button type="button" className="globe-reset" onClick={() => resetViewRef.current?.()}>
          ⟳ Ricentra · nord in alto
        </button>
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
