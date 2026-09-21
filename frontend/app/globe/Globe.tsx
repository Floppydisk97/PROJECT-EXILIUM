"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import {
  biomeLabel, landmassLabel, OCEAN_DEEP, RIVER_MAJOR, RIVER_MINOR, WATER_BIOMES,
  type Tile, type WorldMap,
} from "./biomes";
import {
  buildCliffs, buildGlyphs, buildRivers, buildTerrain, SEA, TERRAIN_FRAG, TERRAIN_LIGHT,
  TERRAIN_VERT, tileAt, tileRadius, tileRing,
} from "./terrain";
import { loadPlanet, PlanetUnavailable } from "../lib/planet";

// The planet is a file now, so the states that described a server are gone with it. There is
// no waking, and no "not generated yet": the asset either ships with the site or the site is
// broken. What remains is a four-megabyte download, which on a phone is worth showing.
type Status = "loading" | "ready" | "error";

// Shells around the planet, in radii. The ground itself and the water it meets are the
// terrain module's business; these are the sky.
const CLOUDS = 1.082;   // cloud deck; the ground is one shell now, so this is pure sky
const RIM = 1.11;       // atmospheric rim drawn over the planet's own limb
const HALO = 1.5;       // outer halo shell; its falloff ends well inside it
const HALO_EDGE = 1.3;  // distance from planet centre where the halo fades to zero

// The hex grid is a tool for picking a tile, not scenery: it fades out at a distance where
// a hundred thousand outlines would only moire, and firms up as the camera closes in.
const GRID_NEAR = 0.15;
const GRID_FAR = 0.028;

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

export default function Globe() {
  const mountRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [selected, setSelected] = useState<Tile | null>(null);
  const highlightRef = useRef<((tile: Tile | null) => void) | null>(null);
  const resetViewRef = useRef<(() => void) | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [progress, setProgress] = useState(0);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    const controllers: { dispose: () => void }[] = [];

    (async () => {
      const abort = new AbortController();
      controllers.push({ dispose: () => abort.abort() });
      let map: WorldMap;
      try {
        map = await loadPlanet(
          (received, total) => {
            if (!disposed) setProgress(Math.min(1, received / Math.max(1, total)));
          },
          abort.signal,
        );
      } catch (reason) {
        if (disposed) return;
        setFailure(reason instanceof PlanetUnavailable ? reason.message : null);
        setStatus("error");
        return;
      }
      if (disposed) return;
      if (!mountRef.current) return;

      const mount = mountRef.current;
      let width = mount.clientWidth;
      let height = mount.clientHeight;

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

      // Unlit like the terrain: the shelf tiles are drawn in flat colour, so a lit shell
      // underneath them would put the two in different colour spaces and leave a seam
      // around every coast.
      scene.add(new THREE.Mesh(
        new THREE.SphereGeometry(SEA, 128, 128),
        new THREE.MeshBasicMaterial({ color: OCEAN_DEEP }),
      ));

      // Geometry is built by the terrain module: pure arithmetic over the columns, kept
      // apart from the scene so it can be tested without a GPU.
      const built = buildTerrain(map);
      const faceTile = built.faceTile;

      const geom = new THREE.BufferGeometry();
      geom.setAttribute("position", new THREE.BufferAttribute(built.positions, 3));
      geom.setAttribute("color", new THREE.BufferAttribute(built.colors, 3));
      geom.setAttribute("grain", new THREE.BufferAttribute(built.grains, 1));
      const terrainMat = new THREE.ShaderMaterial({
        vertexShader: TERRAIN_VERT,
        fragmentShader: TERRAIN_FRAG,
      });
      const terrain = new THREE.Mesh(geom, terrainMat);
      scene.add(terrain);

      const cliffs = buildCliffs(map, built.coast);
      const cliffGeom = new THREE.BufferGeometry();
      cliffGeom.setAttribute("position", new THREE.BufferAttribute(cliffs.positions, 3));
      cliffGeom.setAttribute("color", new THREE.BufferAttribute(cliffs.colors, 3));
      const cliffMat = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide });
      scene.add(new THREE.Mesh(cliffGeom, cliffMat));

      // Hills and mountains are marked inside their own hexagon rather than raised out of
      // it. Double-sided because a glyph's winding follows the tangent frame of wherever it
      // happens to sit on the sphere, and offset forward so the ground cannot nibble it.
      const glyphs = buildGlyphs(map);
      const glyphGeom = new THREE.BufferGeometry();
      glyphGeom.setAttribute("position", new THREE.BufferAttribute(glyphs.positions, 3));
      glyphGeom.setAttribute("color", new THREE.BufferAttribute(glyphs.colors, 3));
      glyphGeom.setDrawRange(0, glyphs.triangles * 3);
      const glyphMat = new THREE.MeshBasicMaterial({
        vertexColors: true, side: THREE.DoubleSide,
        polygonOffset: true, polygonOffsetFactor: -6, polygonOffsetUnits: -6,
      });
      scene.add(new THREE.Mesh(glyphGeom, glyphMat));

      const coastGeom = new THREE.BufferGeometry();
      coastGeom.setAttribute("position", new THREE.BufferAttribute(cliffs.lines, 3));
      const coastMat = new THREE.LineBasicMaterial({
        color: 0x14303f, transparent: true, opacity: 0.35,
      });
      scene.add(new THREE.LineSegments(coastGeom, coastMat));

      const borderGeom = new THREE.BufferGeometry();
      borderGeom.setAttribute("position", new THREE.BufferAttribute(built.borders, 3));
      const borderMat = new THREE.LineBasicMaterial({
        color: 0x14301f, transparent: true, opacity: GRID_FAR,
      });
      scene.add(new THREE.LineSegments(borderGeom, borderMat));

      const rivers = buildRivers(map, RIVER_MINOR, RIVER_MAJOR);
      const riverGeom = new THREE.BufferGeometry();
      riverGeom.setAttribute("position", new THREE.BufferAttribute(rivers.positions, 3));
      riverGeom.setAttribute("color", new THREE.BufferAttribute(rivers.colors, 3));
      riverGeom.setDrawRange(0, rivers.reaches * 6);
      const riverMat = new THREE.MeshBasicMaterial({
        vertexColors: true, side: THREE.DoubleSide,
        // Ribbons lie on ground that steps tile by tile; the offset keeps them from being
        // nibbled by the terrain they run over.
        polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4,
      });
      scene.add(new THREE.Mesh(riverGeom, riverMat));

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
        uniforms: { uColor: { value: new THREE.Color(0x9fd2ff) }, uPower: { value: 3.4 }, uStrength: { value: 0.11 } },
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
          uStrength: { value: 0.11 },
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
        highlight = new THREE.LineLoop(
          new THREE.BufferGeometry().setFromPoints(tileRing(map, tile.index, tileRadius(map, tile.index) * 1.004)),
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
        const hit = raycaster.intersectObject(terrain)[0];
        if (hit && hit.faceIndex != null) {
          const tile = tileAt(map, faceTile[hit.faceIndex]);
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
        const distance = camera.position.length();
        halo.visible = distance > HALO_EDGE + 0.15; // hide once "inside" the air
        // The grid earns its keep when you are close enough to pick a tile, and only
        // moires when you are not.
        borderMat.opacity = THREE.MathUtils.clamp(
          GRID_NEAR + (GRID_FAR - GRID_NEAR) * ((distance - controls.minDistance) / 1.9),
          GRID_FAR, GRID_NEAR,
        );
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
        // Materials and shader programs leak just as readily as geometries, and the retry
        // button rebuilds the whole scene.
        [geom, cliffGeom, glyphGeom, coastGeom, borderGeom, riverGeom].forEach((g) => g.dispose());
        [terrainMat, cliffMat, glyphMat, coastMat, borderMat, riverMat, cloudMat, rimMat, haloMat]
          .forEach((m) => m.dispose());
        if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      } });
    })();

    return () => {
      disposed = true;
      controllers.forEach((c) => c.dispose());
      highlightRef.current = null;
      resetViewRef.current = null;
    };
  }, [reloadKey]);

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
            {/* Only where a river is actually drawn. A lake carries the flow of everything
                that drains into it and passes it out the far side, so its tiles hold a large
                river_flow -- but the reach is the river crossing the lake, not a river
                running through open water, and labelling the lake with it read as a bug. */}
            {!water && selected.river_flow > 0 && (
              <><dt>Corso d&apos;acqua</dt><dd>portata {selected.river_flow}</dd></>
            )}
            <dt>Terra emersa</dt><dd>{water && selected.elevation < 0 ? "—" : landmassLabel(selected.landmass_size)}</dd>
            <dt>Confini</dt><dd>{selected.neighbor_count} tile</dd>
          </dl>
          {water && <p className="globe-panel-note">Acqua: nessuna colonia può insediarsi qui.</p>}
          {!water && selected.elevation >= 0 && (
            /* A tile's ground is decided BY THE TILE, so it can be seen before it is taken:
               the seed no longer mixes in the colony that lands on it. */
            <a className="globe-land" href={`/colonia?tile=${selected.id}`}>
              Scendi sul terreno →
            </a>
          )}
        </aside>
      )}

      {status === "ready" && (
        <button type="button" className="globe-reset" onClick={() => resetViewRef.current?.()}>
          ⟳ Ricentra · nord in alto
        </button>
      )}

      {status !== "ready" && (
        <div className="globe-overlay" role="status">
          {status === "loading" && (
            <p>Caricamento del pianeta…<br />
              <small>{Math.round(progress * 100)} per cento di 4 MB</small>
            </p>
          )}
          {status === "error" && (
            <p>
              Pianeta non caricato.<br />
              <small>{failure ?? "La connessione si è interrotta."}</small><br />
              <button type="button" className="globe-retry"
                      onClick={() => {
                        setFailure(null); setProgress(0);
                        setStatus("loading"); setReloadKey((k) => k + 1);
                      }}>
                Riprova
              </button>
            </p>
          )}
        </div>
      )}

      {status === "ready" && !selected && (
        <p className="globe-hint">Trascina per ruotare · rotellina per zoomare · clicca una terra</p>
      )}
    </div>
  );
}
