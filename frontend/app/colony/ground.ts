// The drawing decisions, separated from the drawing.
//
// Everything here is a pure function of the ground data and a cell's coordinates: which
// colour a cell is, whether a tree stands on it, how big and where exactly. Pulled out of the
// canvas because a renderer is the one place where being wrong is invisible -- it just looks
// like art -- and because a colony that redrew itself differently on every pan would not be a
// place, it would be a screensaver.

export type ColonyGround = {
  name: string;
  label: string;
  seed: string;
  size: number;
  cell_metres: number;
  buildable: number;
  site: {
    biome: string; elevation: number; temperature: number;
    rainfall: number; river_flow: number; coastal: boolean;
  };
  ground_names: string[];
  cells: { ground: number[]; height: number[]; fertility: number[]; vegetation: number[] };
};

/** Ground colours and the words for them. Order follows `citygen.GROUNDS`. */
export const GROUND_STYLE: Record<string, { color: [number, number, number]; label: string }> = {
  deep_water: { color: [28, 52, 72], label: "Acqua profonda" },
  water:      { color: [48, 84, 108], label: "Acqua" },
  marsh:      { color: [72, 80, 60], label: "Acquitrino" },
  sand:       { color: [196, 176, 134], label: "Sabbia" },
  soil:       { color: [96, 78, 56], label: "Terra" },
  gravel:     { color: [126, 120, 106], label: "Ghiaia" },
  rock:       { color: [108, 104, 98], label: "Roccia" },
  ice:        { color: [214, 226, 234], label: "Ghiaccio" },
};

export const WATER = new Set(["deep_water", "water"]);

/** Grass greens the ground it grows on: in this world vegetation is a layer of its own, but a
 *  meadow still reads as green earth and not as brown earth with green dots on it. */
const GRASS: [number, number, number] = [82, 96, 56];

/** A hash, not a random number generator: the same cell must give the same answer for ever,
 *  on every machine, however the camera got there. A seeded PRNG walked forward would depend
 *  on the order cells were drawn in, which changes the moment the viewport does. */
export function hash(seed: number, x: number, y: number, salt: number): number {
  let h = (seed ^ (x * 374761393) ^ (y * 668265263) ^ (salt * 2246822519)) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

export function seedNumber(seed: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < seed.length; i++) {
    h = Math.imul(h ^ seed.charCodeAt(i), 16777619) >>> 0;
  }
  return h >>> 0;
}

export function groundColor(
  ground: ColonyGround, index: number,
): [number, number, number] {
  const name = ground.ground_names[ground.cells.ground[index]];
  const style = GROUND_STYLE[name] ?? GROUND_STYLE.soil;
  if (WATER.has(name) || name === "ice") return style.color;
  // Vegetation greens its own ground, and fertility darkens it: rich earth is not pale.
  const green = Math.min(1, ground.cells.vegetation[index] / 90) * 0.72;
  const rich = 1 - Math.min(1, ground.cells.fertility[index] / 140) * 0.18;
  return [
    (style.color[0] + (GRASS[0] - style.color[0]) * green) * rich,
    (style.color[1] + (GRASS[1] - style.color[1]) * green) * rich,
    (style.color[2] + (GRASS[2] - style.color[2]) * green) * rich,
  ];
}

export type Prop =
  | { kind: "tree" | "bush" | "tuft"; x: number; y: number; size: number; hue: number }
  | { kind: "rock"; x: number; y: number; size: number; hue: number };

/** What stands on a cell. Position is in cell units, so the caller scales it; the jitter is
 *  hashed so a tree never moves between frames, zoom levels or sessions. */
export function propAt(ground: ColonyGround, seed: number, x: number, y: number): Prop | null {
  const index = y * ground.size + x;
  const name = ground.ground_names[ground.cells.ground[index]];
  if (WATER.has(name) || name === "ice") return null;

  const roll = hash(seed, x, y, 1);
  const jx = x + 0.2 + hash(seed, x, y, 2) * 0.6;
  const jy = y + 0.2 + hash(seed, x, y, 3) * 0.6;
  const hue = hash(seed, x, y, 4);

  if (name === "rock") {
    if (roll > 0.22) return null;
    return { kind: "rock", x: jx, y: jy, size: 0.7 + hue * 0.8, hue };
  }

  const veg = ground.cells.vegetation[index];
  if (veg <= 4) return null;
  // Density follows the data, so a rainforest is crowded and a shrubland is sparse without
  // either being a special case.
  const density = Math.min(0.62, veg / 150);
  if (roll > density) return null;
  if (veg > 58 && roll < density * 0.42) {
    return { kind: "tree", x: jx, y: jy, size: 1.5 + hue * 1.3, hue };
  }
  if (veg > 22) return { kind: "bush", x: jx, y: jy, size: 0.55 + hue * 0.35, hue };
  return { kind: "tuft", x: jx, y: jy, size: 0.35 + hue * 0.25, hue };
}

/** The words shown when the cursor is over a cell -- RimWorld's bottom-left corner. */
export function describe(ground: ColonyGround, x: number, y: number): string {
  const index = y * ground.size + x;
  const name = ground.ground_names[ground.cells.ground[index]];
  const style = GROUND_STYLE[name] ?? GROUND_STYLE.soil;
  if (WATER.has(name)) return style.label;
  const fertility = ground.cells.fertility[index];
  return `${style.label} (fert. ${fertility}%)`;
}
