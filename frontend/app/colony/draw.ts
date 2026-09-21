// Drawing a colony the way a colony is drawn: a flat grid of ground, with things standing on
// it that cast shadows. Nothing here is isometric and nothing is three-dimensional -- the
// depth is entirely in the shadow under a tree and in the order the trees are painted.

import {
  ColonyGround, Prop, ROUGHNESS, WATER, hash, litInto, patches, propAt,
} from "./ground";
import { reliefOf } from "./relief";
import { CORNERS, ROW_RATIO, centreX, centreY, mapHeight } from "./hexgrid";

/** Quanti pixel del buffer occupa un esagono in orizzontale, e quante righe di buffer una
 *  riga di esagoni. Due e uno, e non e' una scelta di qualita': e' l'unica coppia che tiene
 *  ALLINEATO lo sfalsamento.
 *
 *  Le righe dispari stanno mezzo esagono a destra. Con un pixel per esagono quel mezzo non ha
 *  dove stare, e il buffer tornerebbe una scacchiera dritta: il colore starebbe mezza cella
 *  fuori dalle linee, a righe alterne, ed e' proprio la cosa che si vedrebbe. Con due pixel,
 *  mezzo esagono e' UN pixel esatto -- niente arrotondamenti, niente ricerca di quale esagono
 *  sta sotto un punto, solo indici interi.
 *
 *  In verticale una riga per riga e basta: le righe non sono sfalsate fra loro, e il buffer
 *  viene poi steso a 0,866 di altezza quando si disegna. A 1536 esagoni sono 3072x1536 pixel,
 *  cioe' 4,7 megapixel -- il doppio di prima e ancora sotto quel che Safari su telefono
 *  alloca (i 9,4 megapixel provati a suo tempo, no).
 *
 *  Sotto questa scala non si disegna niente di quel che sta IN PIEDI sul terreno: a zoom largo
 *  l'inquadratura copre centomila celle, e centomila sagome per fotogramma sono una
 *  presentazione. Il colore del terreno la vegetazione ce l'ha gia' dentro. */
export const SUB_X = 2;
export const PROP_ZOOM = 7;

/** Da quanto vicino si accendono le linee della griglia, se sono accese. Sotto, gli esagoni
 *  sono piu' piccoli dello spessore del tratto: si vedrebbe un velo grigio uniforme, non una
 *  griglia, e a 2,36 milioni di contorni sarebbe anche fermo. */
export const GRID_ZOOM = 9;

/** Paint the ground into an offscreen buffer, once. It never changes, so panning and zooming
 *  are one `drawImage` rather than half a million fills.
 *
 *  Due cose succedono qui: il CONFINE fra due terreni e la GRANA (macchie larghe quanto il
 *  terreno, che stanno nel buffer e quindi si ingrandiscono insieme a lui).
 *
 *  Non c'e' piu' il campionamento bilineare con il bordo spostato a caso che sfumava fra una
 *  cella e l'altra. Non e' una rinuncia: adesso la cella e' un ESAGONO, e il confine fra due
 *  esagoni e' una linea che il gioco tratta come netta -- ci si costruisce sopra. Sfumarlo
 *  sarebbe disegnare una cosa diversa da quella su cui si gioca.
 */
export function paintTerrain(ground: ColonyGround, seed: number): HTMLCanvasElement {
  const size = ground.size;
  const relief = reliefOf(ground);
  const canvas = document.createElement("canvas");
  canvas.width = size * SUB_X;
  canvas.height = size;
  const context = canvas.getContext("2d")!;
  const image = context.createImageData(canvas.width, canvas.height);
  const data = image.data;

  const tint = [0, 0, 0];
  for (let row = 0; row < size; row++) {
    const odd = row & 1;
    // La grana si campiona su due assi alla STESSA densita'. Il buffer non ce l'ha -- due
    // pixel per esagono in orizzontale, uno per riga in verticale -- quindi una macchia
    // presa sugli indici del buffer verrebbe fuori stirata, e un terreno a strisce
    // orizzontali e' esattamente il difetto da cui siamo appena usciti.
    const ny = Math.round(row * SUB_X * ROW_RATIO);
    for (let col = 0; col < size; col++) {
      const index = row * size + col;
      litInto(ground, relief, index, tint);
      const name = ground.ground_names[ground.cells.ground[index]];
      const wet = WATER.has(name);
      const grit = ROUGHNESS[name] ?? 1;
      const leaf = ground.cells.vegetation[index];

      for (let half = 0; half < SUB_X; half++) {
        // Mezzo esagono di scostamento sulle righe dispari, che qui e' un pixel esatto.
        const sx = col * SUB_X + half + odd;
        if (sx >= canvas.width) continue;
        let r = tint[0], g = tint[1], b = tint[2];
        if (wet) {
          // L'acqua non ha grana: ha onde, lunghe e quasi diritte come il vento le fa.
          const wave = Math.sin((sx * 0.35 + ny) * 0.0375 + patches(seed, sx, ny, 31, 80) * 2.2);
          const lift = wave * 2.6 + (patches(seed, sx, ny, 32, 28) - 0.5) * 3.0;
          r += lift * 0.7; g += lift; b += lift * 1.15;
        } else {
          const broad = (patches(seed, sx, ny, 12, 26) - 0.5) * 17 * grit;
          const fine = (hash(seed, sx, ny, 8) - 0.5) * 9 * grit;
          r += broad + fine; g += broad * 0.96 + fine; b += broad * 0.82 + fine;
          // E la chioma: dove c'e' bosco la macchia scurisce in verde invece che in grigio --
          // un bosco visto dall'alto e' fatto di masse e di buchi, non di tinta unita.
          if (leaf > 30) {
            const canopy = (patches(seed, sx, ny, 13, 14) - 0.5) * Math.min(1, (leaf - 30) / 45) * 19;
            r -= canopy * 0.85; g -= canopy * 0.55; b -= canopy * 0.80;
          }
        }
        const at = (row * canvas.width + sx) * 4;
        data[at] = clamp(r);
        data[at + 1] = clamp(g);
        data[at + 2] = clamp(b);
        data[at + 3] = 255;
      }
    }
    // Il primo pixel di una riga dispari resta scoperto: lo sfalsamento ha spinto tutto di
    // uno. Prende il colore del suo vicino invece di restare nero -- mezzo esagono di bordo,
    // e un bordo nero lungo un lato sì e uno no si vedrebbe da qualunque distanza.
    if (odd) {
      const from = (row * canvas.width + 1) * 4;
      const to = row * canvas.width * 4;
      data[to] = data[from]; data[to + 1] = data[from + 1];
      data[to + 2] = data[from + 2]; data[to + 3] = 255;
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
  // L'inquadratura arriva in unita'; le righe pero' distano 0,866, quindi la riga piu' alta
  // visibile non e' `y0` -- e prenderla per tale lascerebbe una striscia di alberi mancanti
  // lungo il bordo superiore, che in panoramica si legge come un lampeggio.
  const x0 = Math.max(0, Math.floor(view.x0) - 2);
  const x1 = Math.min(size - 1, Math.ceil(view.x1) + 1);
  const y0 = Math.max(0, Math.floor(view.y0 / ROW_RATIO) - 2);
  const y1 = Math.min(size - 1, Math.ceil(view.y1 / ROW_RATIO) + 2);
  let drawn = 0;

  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const prop = propAt(ground, seed, x, y);
      if (prop === null) continue;
      drawProp(context, prop, view.scale);
      drawn++;
    }
  }
  return drawn;
}

/** Le linee della griglia, sopra il terreno e sotto le cose che ci stanno in piedi.
 *
 *  Disegnate come VETTORI a risoluzione dello schermo, non cotte dentro il buffer del
 *  terreno. E' quello che le rende accendibili e spegnibili senza rigenerare niente, e anche
 *  quello che le tiene nitide a qualunque ingrandimento: un contorno cotto nel buffer, a due
 *  pixel per esagono, sarebbe una sbavatura grigia.
 *
 *  Un solo `Path2D` per tutta l'inquadratura invece di un tratto per esagono: a diecimila
 *  esagoni visibili, diecimila `stroke()` sono diecimila cambi di stato della tela. */
export function paintHexGrid(
  context: CanvasRenderingContext2D,
  size: number,
  view: { x0: number; y0: number; x1: number; y1: number; scale: number },
): number {
  if (view.scale < GRID_ZOOM) return 0;
  const x0 = Math.max(0, Math.floor(view.x0) - 2);
  const x1 = Math.min(size - 1, Math.ceil(view.x1) + 1);
  const y0 = Math.max(0, Math.floor(view.y0 / ROW_RATIO) - 1);
  const y1 = Math.min(size - 1, Math.ceil(view.y1 / ROW_RATIO) + 1);

  const path = new Path2D();
  let drawn = 0;
  for (let row = y0; row <= y1; row++) {
    const cy = centreY(row) * view.scale;
    for (let col = x0; col <= x1; col++) {
      const cx = centreX(col, row) * view.scale;
      for (let i = 0; i < 6; i++) {
        const [dx, dy] = CORNERS[i];
        const px = cx + dx * view.scale;
        const py = cy + dy * view.scale;
        if (i === 0) path.moveTo(px, py); else path.lineTo(px, py);
      }
      path.closePath();
      drawn++;
    }
  }
  // Piu' si sta vicini, piu' la linea si fa vedere: da lontano una griglia satura e' una
  // rete grigia appoggiata sul terreno, da vicino serve che si legga su cosa si costruisce.
  const closeness = Math.min(1, (view.scale - GRID_ZOOM) / 16);
  context.strokeStyle = `rgba(16, 22, 30, ${0.16 + 0.26 * closeness})`;
  context.lineWidth = Math.max(0.6, view.scale * 0.035);
  context.stroke(path);
  return drawn;
}

/** Il verde della foglia e quello della foglia patita: la terra povera non fa boschi scuri,
 *  fa boschi gialli, ed e' la differenza fra una macchia mediterranea e una foresta. */
const LEAF_DARK: [number, number, number] = [34, 58, 32];
const LEAF_LIT: [number, number, number] = [62, 96, 48];
const DRY_DARK: [number, number, number] = [86, 78, 38];
const DRY_LIT: [number, number, number] = [132, 120, 60];

function tone(
  a: [number, number, number], b: [number, number, number], t: number, shade: number,
): string {
  const k = t < 0 ? 0 : t > 1 ? 1 : t;
  // `shade` non e' piu' la luce del terreno: e' la variazione che la pianta si porta addosso,
  // perche' un bosco di cloni tutti della stessa identica tinta si legge come un timbro.
  const l = Math.max(0.7, Math.min(1.25, shade));
  const r = Math.round(Math.min(255, (a[0] + (b[0] - a[0]) * k) * l));
  const g = Math.round(Math.min(255, (a[1] + (b[1] - a[1]) * k) * l));
  const bl = Math.round(Math.min(255, (a[2] + (b[2] - a[2]) * k) * l));
  return `rgb(${r}, ${g}, ${bl})`;
}

function drawProp(
  context: CanvasRenderingContext2D, prop: Prop, scale: number,
): void {
  const px = prop.x * scale;
  const py = prop.y * scale;
  const s = prop.size * scale;

  // The shadow first, and always down and a little right, so the whole colony agrees about
  // where the light is. Consistency is what makes flat sprites read as standing up -- it is
  // the only third dimension there is here. Questa resta anche dopo che l'ombreggiatura del
  // TERRENO e' sparita: un'ombra corta sotto una pianta dice che la pianta sta in piedi, una
  // fascia lunga mezza mappa non dice niente.
  context.fillStyle = "rgba(14, 18, 26, 0.22)";
  context.beginPath();
  context.ellipse(px + s * 0.16, py + s * 0.10, s * 0.40, s * 0.17, 0, 0, Math.PI * 2);
  context.fill();

  if (prop.kind === "rock") return drawRock(context, prop, px, py, s);
  if (prop.kind === "tuft") return drawTuft(context, prop, px, py, s);
  drawPlant(context, prop, px, py, s);
}

function drawRock(
  context: CanvasRenderingContext2D, prop: Prop, px: number, py: number, s: number,
): void {
  // An irregular polygon, not an ellipse: boulders have corners, and a field of identical
  // grey eggs is what the first attempt looked like.
  const grey = 80 + prop.hue * 46;
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
  context.fillStyle = "rgba(255, 252, 238, 0.12)";
  context.beginPath();
  context.ellipse(px - s * 0.10, py - s * 0.20, s * 0.17, s * 0.11, -0.6, 0, Math.PI * 2);
  context.fill();
}

function drawTuft(
  context: CanvasRenderingContext2D, prop: Prop, px: number, py: number, s: number,
): void {
  context.strokeStyle = tone(LEAF_LIT, DRY_LIT, prop.dry, 0.8 + prop.hue * 0.4);
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
): void {
  const tree = prop.kind === "tree";
  const base = tree ? 0.62 : 0.26;         // how high the canopy sits above the ground
  const spread = tree ? 0.40 : 0.30;

  if (tree) {
    // A tapered trunk, drawn before the canopy so the canopy sits on top of it.
    const bark = 0.85 + prop.hue * 0.3;
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
  const dark = tone(LEAF_DARK, DRY_DARK, prop.dry, 0.9 + prop.hue * 0.2);
  const lit = tone(LEAF_LIT, DRY_LIT, prop.dry, 0.9 + prop.hue * 0.2);
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

