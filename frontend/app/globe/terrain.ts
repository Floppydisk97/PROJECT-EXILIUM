// Turning the render model into geometry. Pure functions over the columns the backend
// sends: no scene, no renderer, nothing that needs a GPU -- which is what lets the tests
// check the arithmetic that the type checker and a screenshot both miss.
import * as THREE from "three";
import {
  biomeColor, biomeGrain, SHELF_DEEP, SHELF_MAX_DEPTH, SHELF_SHALLOW,
  WATER_BIOMES, type Tile, type WorldMap,
} from "./biomes";

// Water sits just under land at elevation zero. The gap used to be 0.005 of a radius --
// thirty kilometres of cliff under every beach; now a coast only rises as far as its own
// ground does, which is what makes a shoreline read as a shoreline.
export const SEA = 0.9982;     // smooth open-ocean shell, beyond the shelf
export const SHELF = 0.9988;   // shallow sea around every coast, above that shell
export const ICE = 0.9994;     // sea ice floats just above the water
export const CLIFF_SHADE = 0.55;  // how much darker a wall is than the ground above it

// All dry land sits on one shell. Elevation decides a tile's colour and which relief glyph
// it carries, never its radius: this is a map, drawn the way a map is drawn, and not a
// scale model of the planet. Extruding each tile to its own height cost more than it paid
// -- every difference in height between two neighbours opened a slit that had to be walled
// shut, and at a glancing angle the mountains hid the ground behind them, which is exactly
// the ground a player is trying to read.
export const GROUND = 1;

// Relief is drawn inside the hexagon instead, the way a paper map marks it. Thresholds in
// metres; on the shipped planet they come out at about one land tile in seven for hills and
// one in ten for mountains, which is dense enough to read as a range and sparse enough that
// the biome underneath still shows.
export const HILL_ELEVATION = 1200;
export const MOUNTAIN_ELEVATION = 2500;
export const GLYPH_SHADE = 0.62;    // how far a glyph is mixed towards the ink below
export const GLYPH_LIFT = 1.0009;   // just off the ground, so it cannot fight it for depth
export const GLYPH_WIDTH = 0.60;    // of one tile's centre-to-centre span
export const GLYPH_HEIGHT = 0.34;
// A glyph is mixed towards this rather than simply darkened, so it keeps the same contrast
// on a snowfield as on rainforest. Multiplying a near-white biome leaves a pale grey mark
// that disappears at the zoom a player actually reads the map at.
export const GLYPH_INK = 0x241f1a;

// The direction the sky is lit from. The ground is not lit at all -- a flat map has no
// slopes to shade, and a biome that changes brightness with where it happens to sit is a
// biome you cannot compare against the legend -- but the cloud deck and the atmosphere are
// scene-lit, and they need a sun.
export const TERRAIN_LIGHT = new THREE.Vector3(0.52, -0.55, 0.65).normalize();

// Rivers are ribbons, not hairlines: a trunk carrying ten times its headwaters' water has
// to look like it. Widths are fractions of a tile, not absolute lengths, so they stay in
// proportion whatever tiling the world is generated at.
export const RIVER_LIFT = 1.0022;
export const RIVER_MIN_HALF = 0.087;   // of one tile's width
export const RIVER_MAX_HALF = 0.278;
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

/** Centre-to-centre distance between neighbouring tiles, on the unit sphere.
 *
 *  Derived from the tile count, not from the frequency: a hexagonal cell whose opposite
 *  sides are d apart covers (sqrt(3)/2) d^2, and the tiles cover the whole sphere. The
 *  module used to use `2*pi / (1.5 * frequency)`, which is 3.48 times too large -- harmless
 *  while every width expressed against it was tuned by eye through the same error, and not
 *  harmless at all the moment something is sized against a real tile, as the relief glyphs
 *  are. The river widths below were re-expressed against this one; they draw the same
 *  ribbons they always did, to within a thousandth of a tile.
 */
export function tileSpacing(map: WorldMap): number {
  return Math.sqrt((8 * Math.PI) / (Math.sqrt(3) * map.tile_count));
}

// Deterministic per-tile jitter: breaks the flatness of a thousand identical hexes without
// inventing geography. The same id always gets the same shade.
export function tileJitter(id: number): number {
  const x = Math.sin(id * 127.1) * 43758.5453;
  return (x - Math.floor(x) - 0.5) * 0.09;
}

/** Which relief a tile reads as. Plain ground carries no glyph at all. */
export function tileRelief(elevation: number): "flat" | "hill" | "mountain" {
  if (elevation >= MOUNTAIN_ELEVATION) return "mountain";
  if (elevation >= HILL_ELEVATION) return "hill";
  return "flat";
}

/** The radius a tile is drawn at: the one ground shell, or the water layer it belongs to.
 *  Land no longer varies with elevation -- see GROUND. */
export function tileRadius(map: WorldMap, index: number): number {
  const elevation = map.tiles.elevation[index];
  if (elevation >= 0) return GROUND;
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

  // An edge shared by two land tiles is inland; one that only a single land tile owns is a
  // shoreline. Corners are already shared indices, so an edge is just its pair of them.
  const edgeOwner = new Map<number, number>();
  const edgePartner = new Map<number, number>();

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

    // A biome is drawn at its own colour wherever it sits, plus the per-tile jitter that
    // keeps a thousand identical hexes from reading as one painted slab. Nothing here
    // depends on which way the tile faces: the ground is flat, so there is no slope to
    // shade, and a green that changes with latitude is a green you cannot match against
    // the legend. Altitude is carried by the glyphs, not by the colour.
    if (dry) {
      tmp.copy(biomeColors[biomeIndex]).multiplyScalar(1 + tileJitter(columns.id[t]));
    } else if (map.biome_names[biomeIndex] === "ocean") {
      // Shelf: real depth, on a curve that lets the pale water fade back into the open sea
      // quickly -- a shelf should read as shallow water, not as an outline stroke.
      const depth = Math.min(1, -elevation / SHELF_MAX_DEPTH);
      tmp.copy(shelfShallow).lerp(shelfDeep, Math.pow(depth, 0.85));
      tmp.multiplyScalar(1 + tileJitter(columns.id[t]) * 0.12);
    } else {
      tmp.copy(biomeColors[biomeIndex]);
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
        if (edgeOwner.has(key)) edgePartner.set(key, t);
        else edgeOwner.set(key, t);
      }
    }
  }

  // Only the shoreline is a step now: inland, every tile is on the same shell, so there is
  // no slit between neighbours left to wall shut.
  const coast: number[] = [];
  for (const [key, owner] of edgeOwner) {
    if (!edgePartner.has(key)) coast.push(key, owner);
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

  const span = tileSpacing(map);
  const minHalf = span * RIVER_MIN_HALF;
  const maxHalf = span * RIVER_MAX_HALF;

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
    // Both ends ride the same shell: the backend still sends each end's elevation, but on a
    // flat map it decides nothing about where the ribbon is drawn.
    const r = GROUND * RIVER_LIFT;
    head.set(columns.a[i * 3] * r, columns.a[i * 3 + 1] * r, columns.a[i * 3 + 2] * r);
    foot.set(columns.b[i * 3] * r, columns.b[i * 3 + 1] * r, columns.b[i * 3 + 2] * r);
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

export type Glyphs = {
  positions: Float32Array;
  colors: Float32Array;
  /** Triangles actually emitted, so the caller can clip the draw. */
  triangles: number;
};

/** Hills and mountains, drawn as a mark inside the tile's own hexagon rather than modelled.
 *
 *  A glyph lives in the tile's tangent plane, with its "up" pointing north, so a range reads
 *  the same way everywhere on the sphere and does not appear to lie on its side once the
 *  camera has been turned around. It is sized as a fraction of the tile's own span, so it
 *  stays in proportion whatever tiling the world was generated at, and it is coloured out of
 *  the ground it sits on, so it stays legible on rock, on snow and on rainforest alike
 *  without a second palette to keep in step.
 *
 *  A hill is one peak; a mountain is a taller peak with a smaller one beside it. The two
 *  meet at their bases and never overlap: coplanar triangles at the same radius would fight
 *  each other for depth, and the flicker is visible exactly where the glyphs are densest.
 */
export function buildGlyphs(map: WorldMap): Glyphs {
  const columns = map.tiles;
  const tileCount = columns.id.length;
  const biomeColors = map.biome_names.map((n) => new THREE.Color(biomeColor(n)));
  const biomeIsWater = map.biome_names.map((n) => WATER_BIOMES.has(n));

  const marked = (t: number) =>
    columns.elevation[t] >= 0 && !biomeIsWater[columns.biome[t]]
      ? tileRelief(columns.elevation[t])
      : "flat";

  // Sized exactly up front: at production tiling a growing array here would churn tens of
  // megabytes for nothing.
  let triangleCount = 0;
  for (let t = 0; t < tileCount; t++) {
    const kind = marked(t);
    if (kind === "hill") triangleCount += 1;
    else if (kind === "mountain") triangleCount += 2;
  }
  const positions = new Float32Array(triangleCount * 9);
  const colors = new Float32Array(triangleCount * 9);

  const span = tileSpacing(map);
  const half = (span * GLYPH_WIDTH) / 2;
  const height = span * GLYPH_HEIGHT;
  const foot = -height * 0.40;

  // [east, north] offsets of each corner, per shape.
  const HILL = [[[-half, foot], [half, foot], [0, foot + height * 0.80]]];
  const MOUNTAIN = [
    [[-half * 0.15, foot], [half, foot], [half * 0.48, foot + height * 1.15]],
    [[-half, foot], [-half * 0.15, foot], [-half * 0.60, foot + height * 0.78]],
  ];

  const up = new THREE.Vector3();
  const north = new THREE.Vector3();
  const east = new THREE.Vector3();
  const colour = new THREE.Color();
  const ink = new THREE.Color(GLYPH_INK);
  const POLE = new THREE.Vector3(0, 0, 1);
  const FALLBACK = new THREE.Vector3(1, 0, 0);

  let v = 0;
  for (let t = 0; t < tileCount; t++) {
    const kind = marked(t);
    if (kind === "flat") continue;

    up.set(columns.center[t * 3], columns.center[t * 3 + 1], columns.center[t * 3 + 2]).normalize();
    // North, flattened into the tangent plane. Directly over a pole there is no north to
    // point at, so any direction in the plane will do and the glyph simply picks one.
    north.copy(POLE).addScaledVector(up, -POLE.dot(up));
    if (north.lengthSq() < 1e-12) north.copy(FALLBACK).addScaledVector(up, -FALLBACK.dot(up));
    north.normalize();
    east.crossVectors(north, up).normalize();

    colour.copy(biomeColors[columns.biome[t]]).lerp(ink, GLYPH_SHADE);
    const shape = kind === "mountain" ? MOUNTAIN : HILL;
    for (const triangle of shape) {
      for (const [e, n] of triangle) {
        // Off the tangent plane and back onto the shell: at this size the difference is
        // under a pixel, but it keeps the glyph from sinking into the ground at the limb.
        const x = (up.x + east.x * e + north.x * n) * GLYPH_LIFT;
        const y = (up.y + east.y * e + north.y * n) * GLYPH_LIFT;
        const z = (up.z + east.z * e + north.z * n) * GLYPH_LIFT;
        positions[v] = x; positions[v + 1] = y; positions[v + 2] = z;
        colors[v] = colour.r; colors[v + 1] = colour.g; colors[v + 2] = colour.b;
        v += 3;
      }
    }
  }
  return { positions, colors, triangles: triangleCount };
}
