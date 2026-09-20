// Drawing a colony the way a colony is drawn: a flat grid of ground, with things standing on
// it that cast shadows. Nothing here is isometric and nothing is three-dimensional -- the
// depth is entirely in the shadow under a tree and in the order the trees are painted.

import {
  ColonyGround, GROUND_STYLE, Prop, WATER, groundColor, hash, propAt,
} from "./ground";

/** Pixels per cell in the terrain buffer. More than one, because a flat square per cell reads
 *  as a spreadsheet: the grain and the blended edges between two grounds are what make it look
 *  like earth, and they need somewhere to live. */
export const SUB = 4;

/** Paint the ground into an offscreen buffer, once. It never changes, so panning and zooming
 *  are one `drawImage` rather than sixteen thousand fills. */
export function paintTerrain(ground: ColonyGround, seed: number): HTMLCanvasElement {
  const size = ground.size;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size * SUB;
  const context = canvas.getContext("2d")!;
  const image = context.createImageData(size * SUB, size * SUB);
  const data = image.data;

  const colors: [number, number, number][] = [];
  for (let i = 0; i < size * size; i++) colors.push(groundColor(ground, i));

  for (let cy = 0; cy < size; cy++) {
    for (let cx = 0; cx < size; cx++) {
      const here = colors[cy * size + cx];
      const name = ground.ground_names[ground.cells.ground[cy * size + cx]];
      const water = WATER.has(name);
      for (let sy = 0; sy < SUB; sy++) {
        for (let sx = 0; sx < SUB; sx++) {
          // Bleed toward whichever neighbour this sub-pixel leans to, with a hashed wobble so
          // the seam between soil and sand is ragged rather than ruled.
          const towardX = sx < SUB / 2 ? -1 : 1;
          const towardY = sy < SUB / 2 ? -1 : 1;
          const lean = Math.abs((sx + 0.5) / SUB - 0.5) + Math.abs((sy + 0.5) / SUB - 0.5);
          const wobble = hash(seed, cx * SUB + sx, cy * SUB + sy, 7);
          let r = here[0], g = here[1], b = here[2];
          if (lean * 1.15 + wobble * 0.45 > 0.62) {
            const nx = Math.min(size - 1, Math.max(0, cx + towardX));
            const ny = Math.min(size - 1, Math.max(0, cy + towardY));
            const near = colors[ny * size + nx];
            r = (r + near[0]) / 2; g = (g + near[1]) / 2; b = (b + near[2]) / 2;
          }
          // A little grain here for large-scale mottling; the fine texture is laid over the
          // top at SCREEN resolution instead, because a buffer of four pixels a cell blown up
          // to forty is a mosaic, and that is exactly what it looked like.
          const grain = (hash(seed, cx * SUB + sx, cy * SUB + sy, 8) - 0.5) * (water ? 7 : 14);
          const at = ((cy * SUB + sy) * size * SUB + (cx * SUB + sx)) * 4;
          data[at] = clamp(r + grain);
          data[at + 1] = clamp(g + grain);
          data[at + 2] = clamp(b + grain);
          data[at + 3] = 255;
        }
      }
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
  const x0 = Math.max(0, Math.floor(view.x0) - 1);
  const x1 = Math.min(size - 1, Math.ceil(view.x1) + 1);
  const y0 = Math.max(0, Math.floor(view.y0) - 1);
  const y1 = Math.min(size - 1, Math.ceil(view.y1) + 1);
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

function drawProp(context: CanvasRenderingContext2D, prop: Prop, scale: number): void {
  const px = prop.x * scale;
  const py = prop.y * scale;
  const s = prop.size * scale;

  // The shadow first, and always down and a little right, so the whole colony agrees about
  // where the light is. Consistency is what makes flat sprites read as standing up -- it is
  // the only third dimension there is here.
  context.fillStyle = "rgba(0, 0, 0, 0.26)";
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
  const grey = 88 + prop.hue * 40;
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
  context.fillStyle = "rgba(255, 255, 255, 0.13)";
  context.beginPath();
  context.ellipse(px - s * 0.10, py - s * 0.20, s * 0.17, s * 0.11, -0.6, 0, Math.PI * 2);
  context.fill();
}

function drawTuft(
  context: CanvasRenderingContext2D, prop: Prop, px: number, py: number, s: number,
): void {
  context.strokeStyle = `rgba(${84 + prop.hue * 24}, ${104 + prop.hue * 30}, ${54}, 0.85)`;
  context.lineWidth = Math.max(0.5, s * 0.16);
  context.lineCap = "round";
  context.beginPath();
  for (let blade = -1; blade <= 1; blade++) {
    context.moveTo(px + blade * s * 0.18, py);
    context.quadraticCurveTo(
      px + blade * s * 0.30, py - s * 0.40,
      px + blade * s * 0.42, py - s * 0.66,
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
    context.fillStyle = `rgb(${58 + prop.hue * 16}, ${40 + prop.hue * 10}, ${26})`;
    context.beginPath();
    context.moveTo(px - s * 0.09, py);
    context.lineTo(px - s * 0.05, py - s * 0.58);
    context.lineTo(px + s * 0.05, py - s * 0.58);
    context.lineTo(px + s * 0.09, py);
    context.closePath();
    context.fill();
  }

  // The canopy: overlapping lobes in two tones, dark underneath and lighter toward the light.
  // One circle is a ball; five off-centre circles are a crown.
  const dark = `rgb(${34 + prop.hue * 16}, ${58 + prop.hue * 26}, ${32 + prop.hue * 12})`;
  const lit = `rgb(${52 + prop.hue * 22}, ${86 + prop.hue * 34}, ${44 + prop.hue * 16})`;
  const lobes = tree ? 5 : 3;
  const cy = py - s * base;

  context.fillStyle = dark;
  for (let lobe = 0; lobe < lobes; lobe++) {
    const angle = (lobe / lobes) * Math.PI * 2 + prop.hue * 4.2;
    context.beginPath();
    context.arc(
      px + Math.cos(angle) * s * spread * 0.55,
      cy + Math.sin(angle) * s * spread * 0.40,
      s * (tree ? 0.30 : 0.24), 0, Math.PI * 2,
    );
    context.fill();
  }
  context.fillStyle = lit;
  for (let lobe = 0; lobe < lobes; lobe++) {
    const angle = (lobe / lobes) * Math.PI * 2 + prop.hue * 4.2;
    context.beginPath();
    context.arc(
      px + Math.cos(angle) * s * spread * 0.50 - s * 0.06,
      cy + Math.sin(angle) * s * spread * 0.36 - s * 0.07,
      s * (tree ? 0.24 : 0.19), 0, Math.PI * 2,
    );
    context.fill();
  }
}

export const LEGEND = GROUND_STYLE;
