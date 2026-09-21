// The drawing decisions, separated from the drawing.
//
// Everything here is a pure function of the ground data and a cell's coordinates: which
// colour a cell is, whether a tree stands on it, how big and where exactly. Pulled out of the
// canvas because a renderer is the one place where being wrong is invisible -- it just looks
// like art -- and because a colony that redrew itself differently on every pan would not be a
// place, it would be a screensaver.

import type { Generated } from "./citygen";
import { shoreCells, type Relief } from "./relief";
import { ROW_RATIO, centreX, centreY } from "./hexgrid";

/** What the drawing needs to know: exactly what the generator produces. The ground is no
 *  longer a file that was baked somewhere else -- it is generated here, from the planet and
 *  the tile -- so the renderer and the generator share one type rather than two that agree. */
export type ColonyGround = Generated;

/** I colori del terreno e le parole per dirlo. L'ordine segue `citygen.GROUNDS`.
 *
 *  Questi sono i colori ASCIUTTI: il colore che quella terra ha in se'. Cio' che si vede passa
 *  da `litColor`, che ci mette sopra l'acqua e la riva. Tenere le due cose separate e' cio'
 *  che permette di ritoccare una tavolozza senza rifare il resto.
 */
export const GROUND_STYLE: Record<string, { color: [number, number, number]; label: string }> = {
  deep_water: { color: [22, 44, 66], label: "Acqua profonda" },
  water:      { color: [46, 86, 112], label: "Acqua" },
  marsh:      { color: [70, 78, 58], label: "Acquitrino" },
  sand:       { color: [178, 160, 124], label: "Sabbia" },
  soil:       { color: [96, 79, 58], label: "Terra" },
  gravel:     { color: [104, 99, 88], label: "Ghiaia" },
  rock:       { color: [86, 84, 81], label: "Roccia" },
  ice:        { color: [206, 219, 229], label: "Ghiaccio" },
};

export const WATER = new Set(["deep_water", "water"]);

/** Quanto e' mossa la superficie di ogni terreno. La roccia non e' grigia LISCIA: in mezzo a
 *  un bosco una rupe senza grana si leggeva come una nuvola bianca appoggiata sopra. */
export const ROUGHNESS: Record<string, number> = {
  rock: 2.0, gravel: 1.7, sand: 0.8, soil: 1.0, marsh: 0.9, ice: 0.5,
};

/** Il verde non e' uno solo. Un prato e un bosco erano lo stesso identico colore, piu' o meno
 *  carico: e' per questo che una foresta sembrava un prato scuro invece che una foresta. */
const MEADOW: [number, number, number] = [96, 110, 62];
const FOREST: [number, number, number] = [48, 68, 42];

/** L'acqua fra la riva e il fondo, e la schiuma dove tocca terra. */
const SHALLOW: [number, number, number] = [72, 126, 136];
const DEEP: [number, number, number] = [22, 46, 72];
const FOAM: [number, number, number] = [156, 190, 188];
/** La sabbia bagnata: l'orlo scuro che segue ogni riva vera. */
const DAMP: [number, number, number] = [78, 72, 60];

function smoothstep(t: number): number {
  const c = t < 0 ? 0 : t > 1 ? 1 : t;
  return c * c * (3 - 2 * c);
}

/** A hash, not a random number generator: the same cell must give the same answer for ever,
 *  on every machine, however the camera got there. A seeded PRNG walked forward would depend
 *  on the order cells were drawn in, which changes the moment the viewport does. */
export function hash(seed: number, x: number, y: number, salt: number): number {
  let h = (seed ^ (x * 374761393) ^ (y * 668265263) ^ (salt * 2246822519)) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

/** Rumore a macchie: lo stesso hash, ma letto su una griglia larga e interpolato. Serve dove
 *  il puntinio non basta -- una chioma e' una MACCHIA, non della polvere verde, e la
 *  differenza fra un bosco e un prato scuro sta tutta qui. */
export function patches(
  seed: number, x: number, y: number, salt: number, span: number,
): number {
  const fx = x / span, fy = y / span;
  const x0 = Math.floor(fx), y0 = Math.floor(fy);
  const tx = smoothstep(fx - x0), ty = smoothstep(fy - y0);
  const a = hash(seed, x0, y0, salt);
  const b = hash(seed, x0 + 1, y0, salt);
  const c = hash(seed, x0, y0 + 1, salt);
  const d = hash(seed, x0 + 1, y0 + 1, salt);
  return (a + (b - a) * tx) + ((c + (d - c) * tx) - (a + (b - a) * tx)) * ty;
}

export function seedNumber(seed: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < seed.length; i++) {
    h = Math.imul(h ^ seed.charCodeAt(i), 16777619) >>> 0;
  }
  return h >>> 0;
}

/** Il colore di una cella prima dell'acqua: di che cosa e' fatta quella terra.
 *
 *  La vegetazione ha due fermate invece di una -- prato e bosco -- perche' con una sola un
 *  bosco era un prato scuro, e infatti e' cosi' che si leggeva.
 *
 *  Scrive dentro un vettore che riceve invece di restituirne uno nuovo. Sembra una pignoleria
 *  e non lo e': il dipinto del terreno chiama questa funzione 590.000 volte di fila, e tre
 *  vettori appena nati per ognuna sono due milioni di oggetti da raccogliere -- mezzo secondo
 *  di caricamento in piu', misurato. Chi vuole la comodita' usa `groundColor`.
 */
export function groundInto(ground: ColonyGround, index: number, out: number[]): void {
  const name = ground.ground_names[ground.cells.ground[index]];
  const style = GROUND_STYLE[name] ?? GROUND_STYLE.soil;
  const color = style.color;
  if (WATER.has(name) || name === "ice") {
    out[0] = color[0]; out[1] = color[1]; out[2] = color[2];
    return;
  }
  const veg = ground.cells.vegetation[index];
  const green = Math.min(1, veg / 85) * 0.82;
  const wood = smoothstep((veg - 42) / 48) * 0.78;
  // Terra ricca e' terra scura: una fertilita' alta non lascia il suolo pallido.
  const rich = 1 - Math.min(1, ground.cells.fertility[index] / 140) * 0.16;
  for (let c = 0; c < 3; c++) {
    const grass = color[c] + (MEADOW[c] - color[c]) * green;
    out[c] = (grass + (FOREST[c] - grass) * wood) * rich;
  }
}

/** Il colore che si VEDE: la terra, piu' l'acqua che la bagna.
 *
 *  Separato da `groundInto` di proposito. Il primo dice cos'e' quel posto, questo dice come
 *  appare adesso: due domande diverse, e la minimappa e la tela devono rispondere alla stessa
 *  seconda domanda o mostrerebbero due colonie diverse.
 *
 *  Qui sopra passava anche l'ombreggiatura del rilievo. Non passa piu': vedi `relief.ts`. */
export function litInto(
  ground: ColonyGround, relief: Relief, index: number, out: number[],
): void {
  const name = ground.ground_names[ground.cells.ground[index]];
  const edge = shoreCells(relief, index);

  if (WATER.has(name)) {
    const deep = relief.depth[index] / 255;
    const sink = smoothstep(deep * 1.5);
    // La schiuma sta nelle prime due celle e mezzo, non in sette: un orlo largo trenta metri
    // non e' una riva, e' una luce al neon lungo tutta la costa. Ed e' come si leggeva.
    const foam = smoothstep(Math.max(0, 1 - edge / 2.5) * (1 - smoothstep(deep * 2.2))) * 0.50;
    for (let c = 0; c < 3; c++) {
      const water = SHALLOW[c] + (DEEP[c] - SHALLOW[c]) * sink;
      out[c] = water + (FOAM[c] - water) * foam;
    }
  } else {
    groundInto(ground, index, out);
    // E l'orlo bagnato e' anche piu' corto: una cella e mezzo. Prima era una strada scura che
    // seguiva il fiume, che e' esattamente cio' che non deve sembrare.
    const damp = Math.max(0, 1 - edge / 1.6) * 0.30;
    for (let c = 0; c < 3; c++) out[c] += (DAMP[c] - out[c]) * damp;
  }
}

const SCRATCH = [0, 0, 0];

/** Le due di sopra, per chi ne vuole uno nuovo invece di riempirne uno suo. */
export function groundColor(ground: ColonyGround, index: number): [number, number, number] {
  groundInto(ground, index, SCRATCH);
  return [SCRATCH[0], SCRATCH[1], SCRATCH[2]];
}

export function litColor(
  ground: ColonyGround, relief: Relief, index: number,
): [number, number, number] {
  litInto(ground, relief, index, SCRATCH);
  return [SCRATCH[0], SCRATCH[1], SCRATCH[2]];
}

export type Prop =
  | { kind: "tree" | "bush" | "tuft"; x: number; y: number; size: number; hue: number;
      dry: number; lean: number }
  | { kind: "rock"; x: number; y: number; size: number; hue: number; dry: number; lean: number };

/** Quanto fitte stanno le piante. La vegetazione della cella dice QUANTE, ma da sola le
 *  distribuisce come una spruzzata uniforme -- e un bosco uniforme non e' un bosco, e' una
 *  carta da parati. Le macchie aprono radure e infittiscono boschetti senza toccare il dato. */
const GROVE_SPAN = 9;

/** What stands on a cell. La posizione esce in LARGHEZZE DI ESAGONO -- non in indici di
 *  cella -- perche' su una griglia sfalsata le due cose non coincidono: una riga dispari sta
 *  mezzo esagono a destra, e un albero piazzato all'indice invece che al centro cadrebbe
 *  mezzo esagono fuori dal suo, a righe alterne. Il tremolio e' hashato, cosi' un albero non
 *  si sposta fra un fotogramma e l'altro, fra uno zoom e l'altro o fra una sessione e l'altra.
 *
 *  Il tremolio resta dentro l'esagono: mezza unita' di ampiezza attorno al centro, che su un
 *  esagono largo uno e' quanto basta perche' un bosco non sia una scacchiera di alberi. */
export function propAt(ground: ColonyGround, seed: number, x: number, y: number): Prop | null {
  const index = y * ground.size + x;
  const name = ground.ground_names[ground.cells.ground[index]];
  if (WATER.has(name) || name === "ice") return null;

  const roll = hash(seed, x, y, 1);
  const jx = centreX(x, y) + (hash(seed, x, y, 2) - 0.5) * 0.5;
  const jy = centreY(y) + (hash(seed, x, y, 3) - 0.5) * 0.5 * ROW_RATIO;
  const hue = hash(seed, x, y, 4);
  // Tre tiri diversi invece di uno riciclato: con un solo numero la pianta grande era sempre
  // anche la piu' chiara e sempre inclinata allo stesso modo, ed e' cosi' che un bosco
  // diventa lo stesso albero timbrato cento volte.
  const bulk = hash(seed, x, y, 14);
  const lean = hash(seed, x, y, 15) - 0.5;
  const fertility = ground.cells.fertility[index];
  // Quanto quella pianta e' patita: terra povera, foglia gialla.
  const dry = Math.max(0, Math.min(1, 1 - fertility / 62)) * (0.45 + 0.55 * hash(seed, x, y, 16));

  if (name === "rock") {
    if (roll > 0.22) return null;
    return { kind: "rock", x: jx, y: jy, size: 0.6 + bulk * 1.0, hue, dry, lean };
  }

  const veg = ground.cells.vegetation[index];
  if (veg <= 4) return null;
  // Density follows the data, so a rainforest is crowded and a shrubland is sparse without
  // either being a special case -- moltiplicata per le macchie, che sono cio' che fa le radure.
  const grove = 0.45 + 1.15 * patches(seed, x, y, 17, GROVE_SPAN);
  const density = Math.min(0.68, (veg / 150) * grove);
  if (roll > density) return null;
  if (veg > 58 && roll < density * 0.42) {
    return { kind: "tree", x: jx, y: jy, size: 1.2 + bulk * 2.0, hue, dry, lean };
  }
  if (veg > 22) return { kind: "bush", x: jx, y: jy, size: 0.45 + bulk * 0.6, hue, dry, lean };
  return { kind: "tuft", x: jx, y: jy, size: 0.30 + bulk * 0.36, hue, dry, lean };
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
