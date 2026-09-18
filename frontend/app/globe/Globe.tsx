"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import {
  biomeColor, biomeGrain, biomeLabel, landmassLabel, OCEAN_DEEP, RIVER_MAJOR, RIVER_MINOR,
  SHELF_DEEP, SHELF_MAX_DEPTH, SHELF_SHALLOW, WATER_BIOMES, type Tile, type WorldMap,
} from "./biomes";

type Status = "loading" | "waking" | "ready" | "ungenerated" | "error";

// The API sleeps on the free plan and needs the better part of a minute to come back. The
// proxy already waits out one cold start; a phone waking a cold stack can still need more
// than one round, so the client keeps asking rather than calling it an outage.
const FETCH_ATTEMPTS = 3;
const FETCH_TIMEOUT_MS = 120_000;
const WAKE_NOTICE_MS = 8_000;

// Water sits just under land at elevation zero. The gap used to be 0.005 of a radius --
// thirty kilometres of cliff under every beach; now a coast only rises as far as its own
// ground does, which is what makes a shoreline read as a shoreline.
const SEA = 0.9982;     // smooth open-ocean shell, beyond the shelf
const SHELF = 0.9988;   // shallow sea around every coast, above that shell
const ICE = 0.9994;     // sea ice floats just above the water
const CLIFF_SHADE = 0.55;  // how much darker a coastal wall is than the ground on top of it
const CLOUDS = 1.082;   // cloud deck, just above the tallest peaks
const RIM = 1.11;       // atmospheric rim drawn over the planet's own limb
const HALO = 1.5;       // outer halo shell; its falloff ends well inside it
const HALO_EDGE = 1.3;  // distance from planet centre where the halo fades to zero
const NORMAL_BLEND = 0.62; // how far terrain normals lean off radial when shading relief
// Terrain is hillshaded by hand against this fixed direction in planet space instead of
// being lit by the scene: a map should stay readable everywhere, so the darkest slope is
// still bright and the limb never falls into shadow. Only the sea uses the scene lights.
const TERRAIN_LIGHT = new THREE.Vector3(0.52, -0.55, 0.65).normalize();
const SHADE_FLOOR = 0.76;   // brightness of a slope facing fully away from the light
const SHADE_RANGE = 0.40;   // extra brightness a slope facing straight into it picks up
const ALTITUDE_TINT = 0.16; // how much brighter the highest ground is than the lowest

// Rivers are ribbons, not hairlines: a trunk carrying ten times its headwaters' water has
// to look like it. Widths are fractions of a tile, not absolute lengths, so they stay in
// proportion whatever tiling the world is generated at.
const RIVER_LIFT = 1.0022;
const RIVER_MIN_HALF = 0.025;   // of one tile's width
const RIVER_MAX_HALF = 0.080;
const RIVER_FULL_FLOW = 240; // flow above the smallest reach at which a river is full width

// The hex grid is a tool for picking a tile, not scenery: it fades out at a distance where
// 24k outlines would only moire, and firms up as the camera closes in.
const GRID_NEAR = 0.15;
const GRID_FAR = 0.028;

// Unlit terrain: the hillshade is already baked into the vertex colours, and the fragment
// shader only adds a fine grain so a biome is not one flat plastic colour up close.
const TERRAIN_VERT = `
  attribute vec3 color;
  attribute float grain;
  varying vec3 vCol; varying vec3 vPos; varying float vGrain;
  void main() {
    vCol = color; vPos = position; vGrain = grain;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;

const TERRAIN_FRAG = `
  varying vec3 vCol; varying vec3 vPos; varying float vGrain;
  float hash(vec3 p){
    p = fract(p * 0.3183099 + vec3(0.71, 0.13, 0.37));
    p *= 23.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
  }
  float noise(vec3 x){
    vec3 i = floor(x); vec3 f = fract(x); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x),
                   mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
                   mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
  }
  void main() {
    // Three octaves is enough texture to read as ground and cheap enough for a phone.
    vec3 p = vPos * 190.0;
    float n = noise(p) * 0.55 + noise(p * 2.3) * 0.3 + noise(p * 5.1) * 0.15;
    gl_FragColor = vec4(vCol * (1.0 + (n - 0.5) * vGrain), 1.0);
  }`;

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
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let disposed = false;
    const controllers: { dispose: () => void }[] = [];

    (async () => {
      // Tell the visitor we are waiting on a sleeping server rather than leaving them on a
      // bare "loading" that looks stuck.
      const wakeNotice = setTimeout(() => { if (!disposed) setStatus("waking"); }, WAKE_NOTICE_MS);
      let map: WorldMap | null = null;
      let missing = false;
      for (let attempt = 0; attempt < FETCH_ATTEMPTS && !disposed; attempt++) {
        try {
          const res = await fetch("/api/map", { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) });
          if (res.status === 404) { missing = true; break; }
          if (res.ok) { map = (await res.json()) as WorldMap; break; }
        } catch {
          // Timed out or the network blinked: fall through and try again.
        }
        if (attempt < FETCH_ATTEMPTS - 1) await new Promise((r) => setTimeout(r, 2000));
      }
      clearTimeout(wakeNotice);
      if (disposed) return;
      if (missing) { setStatus("ungenerated"); return; }
      if (!map) { setStatus("error"); return; }
      if (!mountRef.current) return;

      const mount = mountRef.current;
      let width = mount.clientWidth;
      let height = mount.clientHeight;

      // Relief exaggeration comes from the server together with the terrain normals it
      // computed against it, so geometry and shading can never drift apart.
      const relief = (elevation: number) =>
        1 + Math.min(Math.max(elevation, 0), map.elevation_max) / map.elevation_max * map.relief_gain;

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

      // Terrain: land hexes, the sea ice of the polar caps, and the shelf ring of shallow
      // sea the backend sends around every coast. Everything arrives in columns, and the
      // buffers are sized exactly up front: at production size growing plain arrays would
      // cost a few hundred megabytes of transient garbage on the way.
      const columns = map.tiles;
      const corners = map.corners;
      const cornerCount = corners.length / 3;
      const tileCount = columns.id.length;
      const triangleCount = columns.ring.length;   // one triangle per ring edge
      const vertexCount = triangleCount * 3;

      const biomeNames = map.biome_names;
      const biomeColors = biomeNames.map((n) => new THREE.Color(biomeColor(n)));
      const biomeGrains = biomeNames.map((n) => biomeGrain(n));
      const biomeIsWater = biomeNames.map((n) => WATER_BIOMES.has(n));

      const positions = new Float32Array(vertexCount * 3);
      const colors = new Float32Array(vertexCount * 3);
      const grains = new Float32Array(vertexCount);
      const faceTile = new Uint32Array(triangleCount);

      // Outlines belong to dry, non-water ground only, so count those edges before filling.
      let borderEdges = 0;
      for (let t = 0; t < tileCount; t++) {
        if (columns.elevation[t] >= 0 && !biomeIsWater[columns.biome[t]]) {
          borderEdges += columns.ring_offset[t + 1] - columns.ring_offset[t];
        }
      }
      const borders = new Float32Array(borderEdges * 6);

      const tileRadiusAt = (t: number) =>
        columns.elevation[t] >= 0
          ? relief(columns.elevation[t])
          : biomeNames[columns.biome[t]] === "sea_ice" ? ICE : SHELF;

      const tmp = new THREE.Color();
      // three.js already takes a hex as sRGB and stores it in the renderer's working space,
      // so these are converted once and only once; converting again would darken the whole
      // palette and only show up where a flat material sits next to a vertex colour.
      const shelfShallow = new THREE.Color(SHELF_SHALLOW);
      const shelfDeep = new THREE.Color(SHELF_DEEP);
      const shadeNormal = new THREE.Vector3();

      // An edge shared by two land tiles is inland; one that only a single land tile owns is
      // a shoreline. Corners are already shared indices, so an edge is just its pair of them.
      const edgeOwner = new Map<number, number>();
      const sharedEdges = new Set<number>();

      let v = 0;   // vertex cursor
      let f = 0;   // triangle cursor
      let e = 0;   // border cursor

      for (let t = 0; t < tileCount; t++) {
        const biomeIndex = columns.biome[t];
        const elevation = columns.elevation[t];
        const dry = elevation >= 0;
        const water = biomeIsWater[biomeIndex];
        const r = tileRadiusAt(t);
        const cx = columns.center[t * 3];
        const cy = columns.center[t * 3 + 1];
        const cz = columns.center[t * 3 + 2];

        // Leaning the terrain normal part-way back towards the radial one keeps ranges
        // catching the light without throwing every slope behind them into pitch black.
        // Every tile gets one: the sea ice of the caps is lit by the same hillshade as the
        // land it touches, or the cap reads as a flat plate with a seam along its shore.
        shadeNormal.set(
          cx + (columns.normal[t * 3] - cx) * NORMAL_BLEND,
          cy + (columns.normal[t * 3 + 1] - cy) * NORMAL_BLEND,
          cz + (columns.normal[t * 3 + 2] - cz) * NORMAL_BLEND,
        ).normalize();
        const lambert = SHADE_FLOOR + SHADE_RANGE * Math.max(0, shadeNormal.dot(TERRAIN_LIGHT));

        if (dry) {
          // Height brightens the ground on top of the hillshade, so a highland reads as a
          // highland even where it happens to face away from the light.
          const altitude = Math.min(elevation, map.elevation_max) / map.elevation_max;
          tmp.copy(biomeColors[biomeIndex])
            .multiplyScalar(lambert * (1 + ALTITUDE_TINT * altitude) * (1 + tileJitter(columns.id[t])));
        } else if (biomeNames[biomeIndex] === "ocean") {
          // Shelf: real depth, on a curve that lets the pale water fade back into the open
          // sea quickly -- a shelf should read as shallow water, not as an outline stroke.
          const depth = Math.min(1, -elevation / SHELF_MAX_DEPTH);
          tmp.copy(shelfShallow).lerp(shelfDeep, Math.pow(depth, 0.85));
          tmp.multiplyScalar(1 + tileJitter(columns.id[t]) * 0.12);
        } else {
          tmp.copy(biomeColors[biomeIndex]).multiplyScalar(lambert);
        }
        const grain = biomeGrains[biomeIndex];

        const from = columns.ring_offset[t];
        const to = columns.ring_offset[t + 1];
        const span = to - from;
        for (let i = 0; i < span; i++) {
          const ca = columns.ring[from + i];
          const cb = columns.ring[from + ((i + 1) % span)];
          const ax = corners[ca * 3] * r, ay = corners[ca * 3 + 1] * r, az = corners[ca * 3 + 2] * r;
          const bx = corners[cb * 3] * r, by = corners[cb * 3 + 1] * r, bz = corners[cb * 3 + 2] * r;

          positions[v] = cx * r; positions[v + 1] = cy * r; positions[v + 2] = cz * r;
          positions[v + 3] = ax; positions[v + 4] = ay; positions[v + 5] = az;
          positions[v + 6] = bx; positions[v + 7] = by; positions[v + 8] = bz;
          for (let k = 0; k < 3; k++) {
            colors[v + k * 3] = tmp.r;
            colors[v + k * 3 + 1] = tmp.g;
            colors[v + k * 3 + 2] = tmp.b;
            grains[v / 3 + k] = grain;
          }
          faceTile[f] = t;
          v += 9;
          f += 1;

          // Water has no parcels to outline; a grid over the sea just reads as an artefact.
          if (dry && !water) {
            borders[e] = ax; borders[e + 1] = ay; borders[e + 2] = az;
            borders[e + 3] = bx; borders[e + 4] = by; borders[e + 5] = bz;
            e += 6;
          }
          if (dry) {
            const key = ca < cb ? ca * cornerCount + cb : cb * cornerCount + ca;
            if (edgeOwner.has(key)) sharedEdges.add(key);
            else edgeOwner.set(key, t);
          }
        }
      }

      const geom = new THREE.BufferGeometry();
      geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      geom.setAttribute("grain", new THREE.BufferAttribute(grains, 1));
      const terrain = new THREE.Mesh(geom, new THREE.ShaderMaterial({
        vertexShader: TERRAIN_VERT,
        fragmentShader: TERRAIN_FRAG,
      }));
      scene.add(terrain);

      // Cliffs: every shoreline edge drops a wall to the water, so continents stand on the
      // sea instead of lying flat on it. Drawn double-sided: the ring winding varies.
      const coastKeys: number[] = [];
      for (const [key, owner] of edgeOwner) {
        if (!sharedEdges.has(key)) coastKeys.push(key, owner);
      }
      const coastEdges = coastKeys.length / 2;
      const cliffPositions = new Float32Array(coastEdges * 18);
      const cliffColors = new Float32Array(coastEdges * 18);
      const coastLines = new Float32Array(coastEdges * 6);
      const cliffColor = new THREE.Color();
      for (let i = 0; i < coastEdges; i++) {
        const key = coastKeys[i * 2];
        const owner = coastKeys[i * 2 + 1];
        const ca = Math.floor(key / cornerCount);
        const cb = key % cornerCount;
        const top = tileRadiusAt(owner);
        const atx = corners[ca * 3] * top, aty = corners[ca * 3 + 1] * top, atz = corners[ca * 3 + 2] * top;
        const btx = corners[cb * 3] * top, bty = corners[cb * 3 + 1] * top, btz = corners[cb * 3 + 2] * top;
        // The foot goes to the open-ocean shell, below both the shelf and the sea ice, so
        // no gap can open between the wall and whatever water meets it.
        const afx = corners[ca * 3] * SEA, afy = corners[ca * 3 + 1] * SEA, afz = corners[ca * 3 + 2] * SEA;
        const bfx = corners[cb * 3] * SEA, bfy = corners[cb * 3 + 1] * SEA, bfz = corners[cb * 3 + 2] * SEA;
        const o = i * 18;
        cliffPositions.set([atx, aty, atz, btx, bty, btz, bfx, bfy, bfz,
                            atx, aty, atz, bfx, bfy, bfz, afx, afy, afz], o);
        cliffColor.copy(biomeColors[columns.biome[owner]]).multiplyScalar(CLIFF_SHADE);
        for (let k = 0; k < 6; k++) {
          cliffColors[o + k * 3] = cliffColor.r;
          cliffColors[o + k * 3 + 1] = cliffColor.g;
          cliffColors[o + k * 3 + 2] = cliffColor.b;
        }
        coastLines.set([atx, aty, atz, btx, bty, btz], i * 6);
      }
      const cliffGeom = new THREE.BufferGeometry();
      cliffGeom.setAttribute("position", new THREE.BufferAttribute(cliffPositions, 3));
      cliffGeom.setAttribute("color", new THREE.BufferAttribute(cliffColors, 3));
      scene.add(new THREE.Mesh(cliffGeom, new THREE.MeshBasicMaterial({
        vertexColors: true, side: THREE.DoubleSide,
      })));

      const coastGeom = new THREE.BufferGeometry();
      coastGeom.setAttribute("position", new THREE.BufferAttribute(coastLines, 3));
      scene.add(new THREE.LineSegments(coastGeom, new THREE.LineBasicMaterial({
        color: 0x14303f, transparent: true, opacity: 0.35,
      })));

      const borderGeom = new THREE.BufferGeometry();
      borderGeom.setAttribute("position", new THREE.BufferAttribute(borders, 3));
      const borderMat = new THREE.LineBasicMaterial({
        color: 0x14301f, transparent: true, opacity: GRID_FAR,
      });
      scene.add(new THREE.LineSegments(borderGeom, borderMat));

      // Rivers: the backend already paired each reach with the tile it drains into, so this
      // is a plain list of segments, widened into ribbons in proportion to what they carry.
      const riverColumns = map.rivers;
      const reachCount = riverColumns.flow.length;
      // Centre-to-centre spacing of the tiling this world was generated at.
      const tileSpan = (2 * Math.PI) / (1.5 * map.frequency);
      const riverMinHalf = tileSpan * RIVER_MIN_HALF;
      const riverMaxHalf = tileSpan * RIVER_MAX_HALF;
      const riverPositions = new Float32Array(reachCount * 18);
      const riverColors = new Float32Array(reachCount * 18);
      const head = new THREE.Vector3();
      const foot = new THREE.Vector3();
      const along = new THREE.Vector3();
      const across = new THREE.Vector3();
      const radial = new THREE.Vector3();
      const riverColor = new THREE.Color();
      const riverThin = new THREE.Color(RIVER_MINOR);
      const riverWide = new THREE.Color(RIVER_MAJOR);
      let reaches = 0;
      for (let i = 0; i < reachCount; i++) {
        const ra = relief(riverColumns.ae[i]) * RIVER_LIFT;
        const rb = relief(riverColumns.be[i]) * RIVER_LIFT;
        head.set(riverColumns.a[i * 3] * ra, riverColumns.a[i * 3 + 1] * ra, riverColumns.a[i * 3 + 2] * ra);
        foot.set(riverColumns.b[i * 3] * rb, riverColumns.b[i * 3 + 1] * rb, riverColumns.b[i * 3 + 2] * rb);
        along.subVectors(foot, head);
        if (along.lengthSq() < 1e-12) continue;
        along.normalize();
        radial.copy(head).normalize();
        across.crossVectors(along, radial);
        if (across.lengthSq() < 1e-12) continue;
        const grade = Math.min(1, Math.max(0, (riverColumns.flow[i] - map.river_min_flow) / RIVER_FULL_FLOW));
        const half = riverMinHalf + (riverMaxHalf - riverMinHalf) * grade;
        across.normalize().multiplyScalar(half);
        // Overshoot both ends by a half-width so consecutive reaches meet without a notch.
        head.addScaledVector(along, -half);
        foot.addScaledVector(along, half);
        const o = reaches * 18;
        riverPositions.set([
          head.x - across.x, head.y - across.y, head.z - across.z,
          head.x + across.x, head.y + across.y, head.z + across.z,
          foot.x + across.x, foot.y + across.y, foot.z + across.z,
          head.x - across.x, head.y - across.y, head.z - across.z,
          foot.x + across.x, foot.y + across.y, foot.z + across.z,
          foot.x - across.x, foot.y - across.y, foot.z - across.z,
        ], o);
        riverColor.copy(riverThin).lerp(riverWide, grade);
        for (let k = 0; k < 6; k++) {
          riverColors[o + k * 3] = riverColor.r;
          riverColors[o + k * 3 + 1] = riverColor.g;
          riverColors[o + k * 3 + 2] = riverColor.b;
        }
        reaches += 1;
      }
      const riverGeom = new THREE.BufferGeometry();
      riverGeom.setAttribute("position", new THREE.BufferAttribute(riverPositions, 3));
      riverGeom.setAttribute("color", new THREE.BufferAttribute(riverColors, 3));
      riverGeom.setDrawRange(0, reaches * 6);
      scene.add(new THREE.Mesh(riverGeom, new THREE.MeshBasicMaterial({
        vertexColors: true, side: THREE.DoubleSide,
        // Ribbons lie on ground that steps tile by tile; the offset keeps them from being
        // nibbled by the terrain they run over.
        polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4,
      })));

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
        const r = tileRadiusAt(tile.index) * 1.004;
        const from = columns.ring_offset[tile.index];
        const to = columns.ring_offset[tile.index + 1];
        const pts: THREE.Vector3[] = [];
        for (let i = from; i < to; i++) {
          const c = columns.ring[i];
          pts.push(new THREE.Vector3(corners[c * 3] * r, corners[c * 3 + 1] * r, corners[c * 3 + 2] * r));
        }
        highlight = new THREE.LineLoop(
          new THREE.BufferGeometry().setFromPoints(pts),
          new THREE.LineBasicMaterial({ color: 0xffd34d }),
        );
        scene.add(highlight);
      };

      // The columns stay columns; one tile is only ever materialised for the panel. Latitude
      // and longitude come off the centre vector rather than crossing the wire.
      const tileAt = (index: number): Tile => ({
        index,
        id: columns.id[index],
        lat: THREE.MathUtils.radToDeg(Math.asin(
          Math.min(1, Math.max(-1, columns.center[index * 3 + 2])))),
        lon: THREE.MathUtils.radToDeg(Math.atan2(
          columns.center[index * 3 + 1], columns.center[index * 3])),
        elevation: columns.elevation[index],
        temperature: columns.temperature[index],
        rainfall: columns.rainfall[index],
        biome: biomeNames[columns.biome[index]],
        river_flow: columns.river_flow[index],
        landmass_size: columns.landmass_size[index],
        neighbor_count: columns.neighbor_count[index],
      });

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
          const tile = tileAt(faceTile[hit.faceIndex]);
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
        [geom, cliffGeom, coastGeom, borderGeom, riverGeom].forEach((g) => g.dispose());
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
          {status === "waking" && (
            <p>Risveglio del server…<br />
              <small>Sul piano gratuito la prima apertura può richiedere fino a un minuto.</small>
            </p>
          )}
          {status === "ungenerated" && <p>Il mondo non è ancora stato generato.</p>}
          {status === "error" && (
            <p>
              Server non raggiungibile.<br />
              <small>Si era addormentato e non si è ancora ripreso.</small><br />
              <button type="button" className="globe-retry"
                      onClick={() => { setStatus("loading"); setReloadKey((k) => k + 1); }}>
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
