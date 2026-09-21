// Drawing a colony the way a colony is drawn: a flat grid of ground, with things standing on
// it that cast shadows. Nothing here is isometric and nothing is three-dimensional -- the
// depth is entirely in the shadow under a tree and in the order the trees are painted.

import {
  ColonyGround, Prop, ROUGHNESS, WATER, hash, litInto, patches, propAt,
} from "./ground";
import { lightOf, reliefOf } from "./light";

/** Pixels per cell in the terrain buffer. More than one, because a flat square per cell reads
 *  as a spreadsheet: the blended edges between two grounds need somewhere to live. Two rather
 *  than four, because a colony is 768 cells a side now -- four would be a 3072x3072 buffer,
 *  9.4 megapixels, past what Safari on a phone will allocate. The fine texture is laid over
 *  the top at screen resolution anyway, so the buffer only owes us the blending.
 *
 *  Below this many pixels per cell nothing standing on the ground is drawn: at a wide zoom a
 *  viewport covers a hundred thousand cells, and a hundred thousand sprites a frame is a
 *  slideshow. The terrain already carries the vegetation in its colour. */
export const SUB = 2;
export const PROP_ZOOM = 7;

/** Paint the ground into an offscreen buffer, once. It never changes, so panning and zooming
 *  are one `drawImage` rather than half a million fills.
 *
 *  Tre cose succedono qui, e sono tre difetti che si vedevano tutti nella stessa schermata:
 *  la LUCE (il rilievo, che prima non esisteva: una collina e una piana erano lo stesso
 *  colore), il CONFINE fra due terreni (prima un mezzatinta a caso, adesso un campionamento
 *  bilineare con il bordo spostato a caso, che e' frastagliato senza essere sporco) e la
 *  GRANA (prima puntinio bianco a tutte le scale, adesso macchie larghe quanto il terreno
 *  che stanno nel buffer e quindi si ingrandiscono insieme a lui).
 */
export function paintTerrain(ground: ColonyGround, seed: number): HTMLCanvasElement {
  const size = ground.size;
  const relief = reliefOf(ground);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size * SUB;
  const context = canvas.getContext("2d")!;
  const image = context.createImageData(size * SUB, size * SUB);
  const data = image.data;

  const red = new Float32Array(size * size);
  const green = new Float32Array(size * size);
  const blue = new Float32Array(size * size);
  const wet = new Uint8Array(size * size);
  const leaf = new Uint8Array(size * size);
  const rough = new Float32Array(size * size);
  const tint = [0, 0, 0];
  for (let i = 0; i < size * size; i++) {
    litInto(ground, relief, i, tint);
    red[i] = tint[0]; green[i] = tint[1]; blue[i] = tint[2];
    const name = ground.ground_names[ground.cells.ground[i]];
    wet[i] = WATER.has(name) ? 1 : 0;
    leaf[i] = ground.cells.vegetation[i];
    rough[i] = ROUGHNESS[name] ?? 1;
  }

  const span = size * SUB;
  for (let sy = 0; sy < span; sy++) {
    for (let sx = 0; sx < span; sx++) {
      // Dove cade questo sottopixel, in celle, spostato a caso di una frazione di cella: e'
      // lo spostamento che rende il confine fra sabbia e terra un orlo invece di un righello.
      const wobbleX = (hash(seed, sx, sy, 7) - 0.5) * 0.9;
      const wobbleY = (hash(seed, sx, sy, 11) - 0.5) * 0.9;
      const fx = (sx + 0.5) / SUB - 0.5 + wobbleX;
      const fy = (sy + 0.5) / SUB - 0.5 + wobbleY;
      const x0 = Math.max(0, Math.min(size - 1, Math.floor(fx)));
      const y0 = Math.max(0, Math.min(size - 1, Math.floor(fy)));
      const x1 = Math.min(size - 1, x0 + 1);
      const y1 = Math.min(size - 1, y0 + 1);
      const tx = Math.max(0, Math.min(1, fx - x0));
      const ty = Math.max(0, Math.min(1, fy - y0));
      const i00 = y0 * size + x0, i10 = y0 * size + x1;
      const i01 = y1 * size + x0, i11 = y1 * size + x1;
      const w00 = (1 - tx) * (1 - ty), w10 = tx * (1 - ty);
      const w01 = (1 - tx) * ty, w11 = tx * ty;

      let r = red[i00] * w00 + red[i10] * w10 + red[i01] * w01 + red[i11] * w11;
      let g = green[i00] * w00 + green[i10] * w10 + green[i01] * w01 + green[i11] * w11;
      let b = blue[i00] * w00 + blue[i10] * w10 + blue[i01] * w01 + blue[i11] * w11;

      const here = ty < 0.5 ? (tx < 0.5 ? i00 : i10) : (tx < 0.5 ? i01 : i11);

      if (wet[here]) {
        // L'acqua non ha grana: ha onde, lunghe e quasi diritte come il vento le fa. La
        // prima versione mescolava
        // l'onda con una macchia larga e veniva fuori un corallo cerebrale.
        const wave = Math.sin((sx * 0.35 + sy) * 0.075
                              + patches(seed, sx, sy, 31, 40) * 2.2);
        const lift = wave * 2.6 + (patches(seed, sx, sy, 32, 14) - 0.5) * 3.0;
        r += lift * 0.7; g += lift; b += lift * 1.15;
      } else {
        // Macchie larghe, nel buffer, cosi' crescono col terreno invece di restare polvere
        // sullo schermo. Due frequenze: chiazze di suolo, e sotto di esse il puntinio fine.
        const grit = rough[here];
        const broad = (patches(seed, sx, sy, 12, 13) - 0.5) * 17 * grit;
        const fine = (hash(seed, sx, sy, 8) - 0.5) * 9 * grit;
        r += broad + fine; g += broad * 0.96 + fine; b += broad * 0.82 + fine;
        // E la chioma: dove c'e' bosco, la macchia scurisce in verde invece che in grigio --
        // un bosco visto dall'alto e' fatto di masse e di buchi, non di tinta unita.
        if (leaf[here] > 30) {
          const canopy = (patches(seed, sx, sy, 13, 7) - 0.5)
                       * Math.min(1, (leaf[here] - 30) / 45) * 19;
          r -= canopy * 0.85; g -= canopy * 0.55; b -= canopy * 0.80;
        }
      }

      const at = (sy * span + sx) * 4;
      data[at] = clamp(r);
      data[at + 1] = clamp(g);
      data[at + 2] = clamp(b);
      data[at + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
  return canvas;
}

/** A small tileable sheet of noise, laid over the terrain at screen resolution. This is what
 *  gives ground its texture at any zoom -- without it, terrain is either a mosaic of squares
 *  (nearest neighbour) or a smear (bilinear), and both read as a diagram rather than earth. */
export function makeGrain(seed: number, side = 128): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = side;
  const context = canvas.getContext("2d")!;
  const image = context.createImageData(side, side);
  for (let y = 0; y < side; y++) {
    for (let x = 0; x < side; x++) {
      // Two octaves, so the texture has both speckle and patchiness.
      const fine = hash(seed, x, y, 21);
      const coarse = hash(seed, x >> 2, y >> 2, 22);
      const value = (fine * 0.65 + coarse * 0.35 - 0.5) * 255;
      const at = (y * side + x) * 4;
      image.data[at] = image.data[at + 1] = image.data[at + 2] = value > 0 ? 255 : 0;
      image.data[at + 3] = Math.min(255, Math.abs(value) * 1.5);
    }
  }
  context.putImageData(image, 0, 0);
  return canvas;
}

function clamp(value: number): number {
  return value < 0 ? 0 : value > 255 ? 255 : value | 0;
}

/** Everything standing on the visible ground, painted back to front.
 *
 *  Back to front is the whole trick: a tree lower down the screen is nearer, so it is drawn
 *  last and overlaps the one behind it. That, and the shadow, is the entire third dimension. */
export function paintProps(
  context: CanvasRenderingContext2D,
  ground: ColonyGround,
  seed: number,
  view: { x0: number; y0: number; x1: number; y1: number; scale: number },
): number {
  const size = ground.size;
  if (view.scale < PROP_ZOOM) return 0;
  const relief = reliefOf(ground);
  const x0 = Math.max(0, Math.floor(view.x0) - 1);
  const x1 = Math.min(size - 1, Math.ceil(view.x1) + 1);
  const y0 = Math.max(0, Math.floor(view.y0) - 1);
  const y1 = Math.min(size - 1, Math.ceil(view.y1) + 1);
  let drawn = 0;

  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const prop = propAt(ground, seed, x, y);
      if (prop === null) continue;
      // La pianta prende la luce della cella su cui sta. Senza, un bosco su un fianco in
      // ombra restava verde acceso e sembrava incollato sopra il terreno invece che dentro.
      drawProp(context, prop, view.scale, lightOf(relief, y * size + x));
      drawn++;
    }
  }
  return drawn;
}

/** Il verde della foglia e quello della foglia patita: la terra povera non fa boschi scuri,
 *  fa boschi gialli, ed e' la differenza fra una macchia mediterranea e una foresta. */
const LEAF_DARK: [number, number, number] = [34, 58, 32];
const LEAF_LIT: [number, number, number] = [62, 96, 48];
const DRY_DARK: [number, number, number] = [86, 78, 38];
const DRY_LIT: [number, number, number] = [132, 120, 60];

function tone(
  a: [number, number, number], b: [number, number, number], t: number, light: number,
): string {
  const k = t < 0 ? 0 : t > 1 ? 1 : t;
  const l = Math.max(0.55, Math.min(1.35, light));
  const r = Math.round(Math.min(255, (a[0] + (b[0] - a[0]) * k) * l));
  const g = Math.round(Math.min(255, (a[1] + (b[1] - a[1]) * k) * l));
  const bl = Math.round(Math.min(255, (a[2] + (b[2] - a[2]) * k) * l));
  return `rgb(${r}, ${g}, ${bl})`;
}

function drawProp(
  context: CanvasRenderingContext2D, prop: Prop, scale: number, light: number,
): void {
  const px = prop.x * scale;
  const py = prop.y * scale;
  const s = prop.size * scale;

  // The shadow first, and always down and a little right, so the whole colony agrees about
  // where the light is. Consistency is what makes flat sprites read as standing up -- it is
  // the only third dimension there is here. In ombra l'ombra si smorza: dove non batte il
  // sole non c'e' niente che possa proiettarla.
  context.fillStyle = `rgba(14, 18, 26, ${0.10 + 0.20 * Math.min(1, Math.max(0, light - 0.55))})`;
  context.beginPath();
  context.ellipse(px + s * 0.16, py + s * 0.10, s * 0.40, s * 0.17, 0, 0, Math.PI * 2);
  context.fill();

  if (prop.kind === "rock") return drawRock(context, prop, px, py, s, light);
  if (prop.kind === "tuft") return drawTuft(context, prop, px, py, s, light);
  drawPlant(context, prop, px, py, s, light);
}

function drawRock(
  context: CanvasRenderingContext2D, prop: Prop, px: number, py: number, s: number,
  light: number,
): void {
  // An irregular polygon, not an ellipse: boulders have corners, and a field of identical
  // grey eggs is what the first attempt looked like.
  const grey = (80 + prop.hue * 46) * Math.max(0.6, Math.min(1.3, light));
  const points = 6 + Math.floor(prop.hue * 3);
  context.beginPath();
  for (let i = 0; i < points; i++) {
    const angle = (i / points) * Math.PI * 2 + prop.hue * 5;
    const radius = s * (0.30 + ((Math.sin(i * 12.9898 + prop.hue * 78.233) + 1) / 2) * 0.16);
    const x = px + Math.cos(angle) * radius;
    const y = py - s * 0.10 + Math.sin(angle) * radius * 0.74;
    i === 0 ? context.moveTo(x, y) : context.lineTo(x, y);
  }
  context.closePath();
  context.fillStyle = `rgb(${grey}, ${grey - 3}, ${grey - 10})`;
  context.fill();
  context.strokeStyle = `rgb(${grey - 34}, ${grey - 36}, ${grey - 40})`;
  context.lineWidth = Math.max(0.7, s * 0.05);
  context.stroke();
  // A lit facet, up and to the left, matching the shadow's direction.
  context.fillStyle = `rgba(255, 252, 238, ${0.10 + 0.09 * Math.max(0, light - 1)})`;
  context.beginPath();
  context.ellipse(px - s * 0.10, py - s * 0.20, s * 0.17, s * 0.11, -0.6, 0, Math.PI * 2);
  context.fill();
}

function drawTuft(
  context: CanvasRenderingContext2D, prop: Prop, px: number, py: number, s: number,
  light: number,
): void {
  context.strokeStyle = tone(LEAF_LIT, DRY_LIT, prop.dry, light * (0.8 + prop.hue * 0.4));
  context.lineWidth = Math.max(0.5, s * 0.16);
  context.lineCap = "round";
  context.beginPath();
  for (let blade = -1; blade <= 1; blade++) {
    const tilt = blade + prop.lean * 1.6;
    context.moveTo(px + blade * s * 0.18, py);
    context.quadraticCurveTo(
      px + tilt * s * 0.30, py - s * 0.40,
      px + tilt * s * 0.46, py - s * 0.66,
    );
  }
  context.stroke();
}

function drawPlant(
  context: CanvasRenderingContext2D, prop: Prop, px: number, py: number, s: number,
  light: number,
): void {
  const tree = prop.kind === "tree";
  const base = tree ? 0.62 : 0.26;         // how high the canopy sits above the ground
  const spread = tree ? 0.40 : 0.30;

  if (tree) {
    // A tapered trunk, drawn before the canopy so the canopy sits on top of it.
    const bark = Math.max(0.6, Math.min(1.25, light));
    context.fillStyle = `rgb(${(54 + prop.hue * 22) * bark}, ${(38 + prop.hue * 14) * bark}, ${26 * bark})`;
    context.beginPath();
    context.moveTo(px - s * 0.09, py);
    context.lineTo(px - s * 0.05 + prop.lean * s * 0.20, py - s * 0.58);
    context.lineTo(px + s * 0.05 + prop.lean * s * 0.20, py - s * 0.58);
    context.lineTo(px + s * 0.09, py);
    context.closePath();
    context.fill();
  }

  // The canopy: overlapping lobes in two tones, dark underneath and lighter toward the light.
  // One circle is a ball; five off-centre circles are a crown. Il numero dei lobi e la loro
  // schiacciatura cambiano da pianta a pianta: cinque cerchi sempre uguali sono un timbro.
  const dark = tone(LEAF_DARK, DRY_DARK, prop.dry, light * (0.9 + prop.hue * 0.2));
  const lit = tone(LEAF_LIT, DRY_LIT, prop.dry, light * (0.9 + prop.hue * 0.2));
  const lobes = (tree ? 4 : 3) + Math.floor(prop.hue * 3);
  const squash = 0.34 + prop.dry * 0.12 + prop.hue * 0.12;
  const cx = px + prop.lean * s * 0.22;
  const cy = py - s * base;
  const turn = prop.hue * 6.283;

  context.fillStyle = dark;
  for (let lobe = 0; lobe < lobes; lobe++) {
    const angle = (lobe / lobes) * Math.PI * 2 + turn;
    context.beginPath();
    context.arc(
      cx + Math.cos(angle) * s * spread * 0.58,
      cy + Math.sin(angle) * s * spread * squash * 1.15,
      s * (tree ? 0.30 : 0.24) * (0.85 + prop.lean * 0.3), 0, Math.PI * 2,
    );
    context.fill();
  }
  context.fillStyle = lit;
  for (let lobe = 0; lobe < lobes; lobe++) {
    const angle = (lobe / lobes) * Math.PI * 2 + turn;
    context.beginPath();
    context.arc(
      cx + Math.cos(angle) * s * spread * 0.50 - s * 0.07,
      cy + Math.sin(angle) * s * spread * squash - s * 0.08,
      s * (tree ? 0.23 : 0.18) * (0.85 + prop.lean * 0.3), 0, Math.PI * 2,
    );
    context.fill();
  }
}

