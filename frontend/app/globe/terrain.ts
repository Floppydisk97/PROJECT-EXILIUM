// Turning the render model into geometry. Pure functions over the columns the backend
// sends: no scene, no renderer, nothing that needs a GPU -- which is what lets the tests
// check the arithmetic that the type checker and a screenshot both miss.
import * as THREE from "three";
import {
  biomeColor, biomeGrain, SHELF_DEEP, SHELF_MAX_DEPTH, SHELF_SHALLOW, WATER_BIOMES,
  type Tile, type WorldMap,
} from "./biomes";

// Water sits just under land at elevation zero. The gap used to be 0.005 of a radius --
// thirty kilometres of cliff under every beach; now a coast only rises as far as its own
// ground does, which is what makes a shoreline read as a shoreline.
export const SEA = 0.9982;     // smooth open-ocean shell, beyond the shelf
export const SHELF = 0.9988;   // shallow sea around every coast, above that shell
export const ICE = 0.9994;     // sea ice floats just above the water
export const CLIFF_SHADE = 0.55;  // how much darker a coastal wall is than the ground above it

// Terrain is hillshaded by hand against this fixed direction in planet space instead of
// being lit by the scene: a map should stay readable everywhere, so the darkest slope is
// still bright and the limb never falls into shadow.
export const TERRAIN_LIGHT = new THREE.Vector3(0.52, -0.55, 0.65).normalize();
export const NORMAL_BLEND = 0.62; // how far terrain normals lean off radial when shading
export const SHADE_FLOOR = 0.76;  // brightness of a slope facing fully away from the light
export const SHADE_RANGE = 0.40;  // extra brightness a slope facing straight into it picks up
export const ALTITUDE_TINT = 0.16; // how much brighter the highest ground is than the lowest

// Rivers are ribbons, not hairlines: a trunk carrying ten times its headwaters' water has
// to look like it. Widths are fractions of a tile, not absolute lengths, so they stay in
// proportion whatever tiling the world is generated at.
export const RIVER_LIFT = 1.0022;
export const RIVER_MIN_HALF = 0.025;   // of one tile's width
export const RIVER_MAX_HALF = 0.080;
export const RIVER_FULL_FLOW = 240;    // flow above the smallest reach at which a river is full width

// Unlit terrain: the hillshade is already baked into the vertex colours, and the fragment
// shader only adds a fine grain so a biome is not one flat plastic colour up close.
export const TERRAIN_VERT = `
  attribute vec3 color;
  attribute float grain;
  varying vec3 vCol; varying vec3 vPos; varying float vGrain;
  void main() {
    vCol = color; vPos = position; vGrain = grain;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;

export const TERRAIN_FRAG = `
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

// Deterministic per-tile jitter: breaks the flatness of a thousand identical hexes without
// inventing geography. The same id always gets the same shade.
export function tileJitter(id: number): number {
  const x = Math.sin(id * 127.1) * 43758.5453;
  return (x - Math.floor(x) - 0.5) * 0.09;
}

/** Relief exaggeration, taken from the server together with the normals it computed
 *  against it, so geometry and shading can never drift apart. */
export function relief(map: WorldMap, elevation: number): number {
  const height = Math.min(Math.max(elevation, 0), map.elevation_max) / map.elevation_max;
  return 1 + height * map.relief_gain;
}

/** The radius a tile is drawn at: its own ground, or the water layer it belongs to. */
export function tileRadius(map: WorldMap, index: number): number {
  const elevation = map.tiles.elevation[index];
  if (elevation >= 0) return relief(map, elevation);
  return map.biome_names[map.tiles.biome[index]] === "sea_ice" ? ICE : SHELF;
}

/** One tile, materialised only when the panel needs to show it. Latitude and longitude
 *  are derived here rather than sent: the centre vector already carries them. */
export function tileAt(map: WorldMap, index: number): Tile {
  const c = map.tiles.center;
  return {
    index,
    id: map.tiles.id[index],
    lat: THREE.MathUtils.radToDeg(Math.asin(Math.min(1, Math.max(-1, c[index * 3 + 2])))),
    lon: THREE.MathUtils.radToDeg(Math.atan2(c[index * 3 + 1], c[index * 3])),
    elevation: map.tiles.elevation[index],
    temperature: map.tiles.temperature[index],
    rainfall: map.tiles.rainfall[index],
    biome: map.biome_names[map.tiles.biome[index]],
    river_flow: map.tiles.river_flow[index],
    landmass_size: map.tiles.landmass_size[index],
    neighbor_count: map.tiles.neighbor_count[index],
  };
}

/** A tile's polygon ring, at a radius of the caller's choosing. */
export function tileRing(map: WorldMap, index: number, radius: number): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  for (let i = map.tiles.ring_offset[index]; i < map.tiles.ring_offset[index + 1]; i++) {
    const c = map.tiles.ring[i];
    points.push(new THREE.Vector3(
      map.corners[c * 3] * radius,
      map.corners[c * 3 + 1] * radius,
      map.corners[c * 3 + 2] * radius,
    ));
  }
  return points;
}

export type Terrain = {
  positions: Float32Array;
  colors: Float32Array;
  grains: Float32Array;
  /** Triangle index -> tile index, for picking. */
  faceTile: Uint32Array;
  /** Hex outlines, dry non-water ground only. */
  borders: Float32Array;
  /** Shoreline edges as [packedEdgeKey, owningTileIndex] pairs. */
  coast: number[];
};

/** Land hexes, the sea ice of the polar caps, and the shelf ring of shallow sea around
 *  every coast. Buffers are sized exactly up front: at production size growing plain
 *  arrays would cost a few hundred megabytes of transient garbage on the way. */
export function buildTerrain(map: WorldMap): Terrain {
  const columns = map.tiles;
  const corners = map.corners;
  const cornerCount = corners.length / 3;
  const tileCount = columns.id.length;
  const triangleCount = columns.ring.length;   // one triangle per ring edge

  const biomeColors = map.biome_names.map((n) => new THREE.Color(biomeColor(n)));
  const biomeGrains = map.biome_names.map((n) => biomeGrain(n));
  const biomeIsWater = map.biome_names.map((n) => WATER_BIOMES.has(n));

  const positions = new Float32Array(triangleCount * 9);
  const colors = new Float32Array(triangleCount * 9);
  const grains = new Float32Array(triangleCount * 3);
  const faceTile = new Uint32Array(triangleCount);

  // Outlines belong to dry, non-water ground only, so count those edges before filling.
  let borderEdges = 0;
  for (let t = 0; t < tileCount; t++) {
    if (columns.elevation[t] >= 0 && !biomeIsWater[columns.biome[t]]) {
      borderEdges += columns.ring_offset[t + 1] - columns.ring_offset[t];
    }
  }
  const borders = new Float32Array(borderEdges * 6);

  const tmp = new THREE.Color();
  // three.js already takes a hex as sRGB and stores it in the renderer's working space,
  // so these are converted once and only once; converting again would darken the whole
  // palette and only show up where a flat material sits next to a vertex colour.
  const shelfShallow = new THREE.Color(SHELF_SHALLOW);
  const shelfDeep = new THREE.Color(SHELF_DEEP);
  const shadeNormal = new THREE.Vector3();

  // An edge shared by two land tiles is inland; one that only a single land tile owns is a
  // shoreline. Corners are already shared indices, so an edge is just its pair of them.
  const edgeOwner = new Map<number, number>();
  const sharedEdges = new Set<number>();

  let v = 0;   // vertex cursor, in floats
  let f = 0;   // triangle cursor
  let e = 0;   // border cursor, in floats

  for (let t = 0; t < tileCount; t++) {
    const biomeIndex = columns.biome[t];
    const elevation = columns.elevation[t];
    const dry = elevation >= 0;
    const water = biomeIsWater[biomeIndex];
    const r = tileRadius(map, t);
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
    } else if (map.biome_names[biomeIndex] === "ocean") {
      // Shelf: real depth, on a curve that lets the pale water fade back into the open sea
      // quickly -- a shelf should read as shallow water, not as an outline stroke.
      const depth = Math.min(1, -elevation / SHELF_MAX_DEPTH);
      tmp.copy(shelfShallow).lerp(shelfDeep, Math.pow(depth, 0.85));
      tmp.multiplyScalar(1 + tileJitter(columns.id[t]) * 0.12);
    } else {
      tmp.copy(biomeColors[biomeIndex]).multiplyScalar(lambert);
    }
    const grain = biomeGrains[biomeIndex];

    const from = columns.ring_offset[t];
    const span = columns.ring_offset[t + 1] - from;
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

  const coast: number[] = [];
  for (const [key, owner] of edgeOwner) {
    if (!sharedEdges.has(key)) coast.push(key, owner);
  }
  return { positions, colors, grains, faceTile, borders, coast };
}

export type Cliffs = {
  positions: Float32Array;
  colors: Float32Array;
  /** The shoreline itself, as line segments along the top of each wall. */
  lines: Float32Array;
};

/** Every shoreline edge drops a wall to the water, so continents stand on the sea instead
 *  of lying flat on it. Drawn double-sided by the caller: the ring winding varies. */
export function buildCliffs(map: WorldMap, coast: number[]): Cliffs {
  const corners = map.corners;
  const cornerCount = corners.length / 3;
  const edges = coast.length / 2;
  const positions = new Float32Array(edges * 18);
  const colors = new Float32Array(edges * 18);
  const lines = new Float32Array(edges * 6);
  const biomeColors = map.biome_names.map((n) => new THREE.Color(biomeColor(n)));
  const colour = new THREE.Color();

  for (let i = 0; i < edges; i++) {
    const key = coast[i * 2];
    const owner = coast[i * 2 + 1];
    const ca = Math.floor(key / cornerCount);
    const cb = key % cornerCount;
    const top = tileRadius(map, owner);
    const atx = corners[ca * 3] * top, aty = corners[ca * 3 + 1] * top, atz = corners[ca * 3 + 2] * top;
    const btx = corners[cb * 3] * top, bty = corners[cb * 3 + 1] * top, btz = corners[cb * 3 + 2] * top;
    // The foot goes to the open-ocean shell, below both the shelf and the sea ice, so no
    // gap can open between the wall and whatever water meets it.
    const afx = corners[ca * 3] * SEA, afy = corners[ca * 3 + 1] * SEA, afz = corners[ca * 3 + 2] * SEA;
    const bfx = corners[cb * 3] * SEA, bfy = corners[cb * 3 + 1] * SEA, bfz = corners[cb * 3 + 2] * SEA;
    const o = i * 18;
    positions.set([atx, aty, atz, btx, bty, btz, bfx, bfy, bfz,
                   atx, aty, atz, bfx, bfy, bfz, afx, afy, afz], o);
    colour.copy(biomeColors[map.tiles.biome[owner]]).multiplyScalar(CLIFF_SHADE);
    for (let k = 0; k < 6; k++) {
      colors[o + k * 3] = colour.r;
      colors[o + k * 3 + 1] = colour.g;
      colors[o + k * 3 + 2] = colour.b;
    }
    lines.set([atx, aty, atz, btx, bty, btz], i * 6);
  }
  return { positions, colors, lines };
}

export type Rivers = {
  positions: Float32Array;
  colors: Float32Array;
  /** Reaches actually emitted; degenerate ones are skipped, so the caller clips the draw. */
  reaches: number;
};

/** The backend already paired each reach with the tile it drains into, so this is a plain
 *  list of segments, widened into ribbons in proportion to what they carry. */
export function buildRivers(map: WorldMap, minor: number, major: number): Rivers {
  const columns = map.rivers;
  const count = columns.flow.length;
  const positions = new Float32Array(count * 18);
  const colors = new Float32Array(count * 18);

  // Centre-to-centre spacing of the tiling this world was generated at.
  const tileSpan = (2 * Math.PI) / (1.5 * map.frequency);
  const minHalf = tileSpan * RIVER_MIN_HALF;
  const maxHalf = tileSpan * RIVER_MAX_HALF;

  const head = new THREE.Vector3();
  const foot = new THREE.Vector3();
  const along = new THREE.Vector3();
  const across = new THREE.Vector3();
  const radial = new THREE.Vector3();
  const colour = new THREE.Color();
  const thin = new THREE.Color(minor);
  const wide = new THREE.Color(major);

  let reaches = 0;
  for (let i = 0; i < count; i++) {
    const ra = relief(map, columns.ae[i]) * RIVER_LIFT;
    const rb = relief(map, columns.be[i]) * RIVER_LIFT;
    head.set(columns.a[i * 3] * ra, columns.a[i * 3 + 1] * ra, columns.a[i * 3 + 2] * ra);
    foot.set(columns.b[i * 3] * rb, columns.b[i * 3 + 1] * rb, columns.b[i * 3 + 2] * rb);
    along.subVectors(foot, head);
    if (along.lengthSq() < 1e-12) continue;
    along.normalize();
    radial.copy(head).normalize();
    across.crossVectors(along, radial);
    if (across.lengthSq() < 1e-12) continue;
    const grade = Math.min(1, Math.max(0, (columns.flow[i] - map.river_min_flow) / RIVER_FULL_FLOW));
    const half = minHalf + (maxHalf - minHalf) * grade;
    across.normalize().multiplyScalar(half);
    // Overshoot both ends by a half-width so consecutive reaches meet without a notch.
    head.addScaledVector(along, -half);
    foot.addScaledVector(along, half);
    const o = reaches * 18;
    positions.set([
      head.x - across.x, head.y - across.y, head.z - across.z,
      head.x + across.x, head.y + across.y, head.z + across.z,
      foot.x + across.x, foot.y + across.y, foot.z + across.z,
      head.x - across.x, head.y - across.y, head.z - across.z,
      foot.x + across.x, foot.y + across.y, foot.z + across.z,
      foot.x - across.x, foot.y - across.y, foot.z - across.z,
    ], o);
    colour.copy(thin).lerp(wide, grade);
    for (let k = 0; k < 6; k++) {
      colors[o + k * 3] = colour.r;
      colors[o + k * 3 + 1] = colour.g;
      colors[o + k * 3 + 2] = colour.b;
    }
    reaches += 1;
  }
  return { positions, colors, reaches };
}
