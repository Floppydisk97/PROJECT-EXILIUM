// Il pittore del terreno: 319 righe che nessun test guardava.
//
// E' la cosa che si vede ogni volta che si apre il gioco, ed e' anche il posto dove sbagliare
// non si vede: viene fuori un terreno un po' strano, e un terreno un po' strano sembra una
// scelta grafica. Qui stanno le cose che NON sono scelte.
//
// La piu' importante e' lo SFALSAMENTO. Le righe dispari stanno mezzo esagono a destra, e nel
// buffer quel mezzo esagono e' esattamente un pixel: se si perdesse, il colore starebbe mezza
// cella fuori dalle linee a righe alterne -- visibile a chiunque guardi, invisibile a
// qualunque test che non lo misuri.
//
// Non c'e' una tela, qui: i test girano in node. Se ne costruisce una finta, che registra i
// pixel invece di disegnarli. E' abbastanza, perche' quel che si vuole sapere e' quali pixel
// ha toccato e di che colore -- non come appaiono.
import { describe, expect, it } from "vitest";
import { GRID_ZOOM, PROP_ZOOM, SUB_X, paintHexGrid, paintProps, paintTerrain } from "./draw";
import { seedNumber, type ColonyGround } from "./ground";

const NAMES = ["deep_water", "water", "marsh", "sand", "soil", "gravel", "rock", "ice"];
const SOIL = NAMES.indexOf("soil");
const WATER = NAMES.indexOf("water");

class FakeImageData {
  data: Uint8ClampedArray;
  constructor(public width: number, public height: number) {
    this.data = new Uint8ClampedArray(width * height * 4);
  }
}

/** Una tela che non disegna: conta le chiamate e tiene i pixel. */
function fakeCanvas() {
  const calls: Record<string, number> = {};
  const context: Record<string, unknown> = {
    createImageData: (w: number, h: number) => new FakeImageData(w, h),
    putImageData: (image: FakeImageData) => { canvas.image = image; },
  };
  // Tutto il resto -- `beginPath`, `arc`, `fill`... -- e' un metodo che non fa niente e si
  // segna di essere stato chiamato. Cosi' il disegno delle sagome gira davvero, e si puo'
  // chiedere QUANTO ha disegnato senza avere una tela vera.
  const recorder = new Proxy(context, {
    get(target, key: string) {
      if (key in target) return target[key];
      return (...args: unknown[]) => { calls[key] = (calls[key] ?? 0) + 1; return args; };
    },
    set(target, key: string, value) { target[key] = value; return true; },
  });
  const canvas = {
    width: 0, height: 0, image: null as FakeImageData | null, calls,
    getContext: () => recorder,
  };
  return canvas;
}

// Al livello del MODULO e non dentro `beforeAll`: i corpi dei `describe` girano in fase di
// raccolta, prima di qualunque gancio, e li' dentro si dipinge gia'.
(globalThis as Record<string, unknown>).document = {
  createElement: () => fakeCanvas(),
};
// `Path2D` non esiste in node, e la griglia ne costruisce uno solo per tutta l'inquadratura.
(globalThis as Record<string, unknown>).Path2D = class {
  moveTo() {} lineTo() {} closePath() {}
};

function colony(size: number, at: (col: number, row: number) => number): ColonyGround {
  const ground = new Uint8Array(size * size);
  const height = new Int32Array(size * size);
  const fertility = new Uint8Array(size * size);
  const vegetation = new Uint8Array(size * size);
  for (let row = 0; row < size; row++) {
    for (let col = 0; col < size; col++) {
      ground[row * size + col] = at(col, row);
      fertility[row * size + col] = 40;
      vegetation[row * size + col] = 30;
    }
  }
  return {
    seed: "seed", size, hex_width_m: 1.0745699318235418, buildable: 0,
    economy: { food: 0, timber: 0, stone: 0, ore: 0, wind: 0, sun: 0, water: 0, heat: 0, effort: 0, room: 0 },
    site: { biome: "temperate_forest", elevation: 100, temperature: 10, rainfall: 900, river_flow: 0, coastal: false },
    ground_names: NAMES,
    cells: { ground, height, fertility, vegetation },
  };
}

function pixel(image: FakeImageData, sx: number, sy: number) {
  const at = (sy * image.width + sx) * 4;
  return { r: image.data[at], g: image.data[at + 1], b: image.data[at + 2], a: image.data[at + 3] };
}

/** L'acqua e' blu: piu' blu che rossa. La terra, in qualunque tinta di questa tavolozza, no.
 *  Serve un criterio ROBUSTO perche' sopra il colore c'e' la grana, che cambia a ogni pixel. */
const isWater = (p: { r: number; b: number }) => p.b > p.r;

describe("il buffer del terreno", () => {
  const size = 16;
  const made = paintTerrain(colony(size, () => SOIL), seedNumber("x")) as unknown as
    ReturnType<typeof fakeCanvas>;

  it("ha due pixel per esagono in orizzontale e una riga per riga", () => {
    // Non una scelta di qualita': e' l'unica coppia in cui mezzo esagono di sfalsamento e'
    // un numero intero di pixel.
    expect(made.width).toBe(size * SUB_X);
    expect(made.height).toBe(size);
    expect(made.image!.width).toBe(size * SUB_X);
  });

  it("non lascia un solo pixel scoperto", () => {
    // Lo sfalsamento spinge le righe dispari di uno, quindi il loro primo pixel resterebbe
    // nero: un bordo scuro lungo una riga sì e una no, visibile da qualunque distanza.
    const image = made.image!;
    for (let sy = 0; sy < image.height; sy++) {
      for (let sx = 0; sx < image.width; sx++) {
        expect(pixel(image, sx, sy).a, `pixel scoperto a ${sx},${sy}`).toBe(255);
      }
    }
  });
});

describe("lo sfalsamento delle righe dispari", () => {
  const size = 16;

  it("sposta una riga dispari di esattamente un pixel, e non tocca le pari", () => {
    // Una cella d'acqua sola in mezzo alla terra, su una riga pari e su una dispari. Dove
    // finisce il blu dice dove il pittore crede che stia quella cella.
    for (const row of [4, 5]) {
      const col = 6;
      const ground = colony(size, (c, r) => (c === col && r === row ? WATER : SOIL));
      const image = (paintTerrain(ground, seedNumber("y")) as unknown as
        ReturnType<typeof fakeCanvas>).image!;
      const odd = row & 1;
      const first = col * SUB_X + odd;

      expect(isWater(pixel(image, first, row)), `riga ${row}: atteso blu a ${first}`).toBe(true);
      expect(isWater(pixel(image, first + 1, row)), `riga ${row}: atteso blu a ${first + 1}`).toBe(true);
      // E i vicini immediati NON sono acqua: se lo fossero, la cella sarebbe larga tre pixel
      // -- cioe' lo sfalsamento starebbe sbavando su chi le sta accanto.
      expect(isWater(pixel(image, first - 1, row)), `riga ${row}: ${first - 1} non deve essere blu`).toBe(false);
      expect(isWater(pixel(image, first + 2, row)), `riga ${row}: ${first + 2} non deve essere blu`).toBe(false);
    }
  });

  it("mette l'acqua in due colonne DIVERSE a seconda che la riga sia pari o dispari", () => {
    // La prova che lo sfalsamento esiste davvero. Se sparisse, ogni test qui sopra
    // continuerebbe a passare con `odd` sempre zero -- e il terreno sarebbe una scacchiera.
    const col = 6;
    const even = (paintTerrain(colony(size, (c, r) => (c === col && r === 4 ? WATER : SOIL)),
      seedNumber("z")) as unknown as ReturnType<typeof fakeCanvas>).image!;
    const odd = (paintTerrain(colony(size, (c, r) => (c === col && r === 5 ? WATER : SOIL)),
      seedNumber("z")) as unknown as ReturnType<typeof fakeCanvas>).image!;
    expect(isWater(pixel(even, col * SUB_X, 4))).toBe(true);
    expect(isWater(pixel(odd, col * SUB_X, 5))).toBe(false);
  });
});

describe("quel che si disegna solo da vicino", () => {
  const ground = colony(24, () => SOIL);
  const view = (scale: number) => ({ x0: 0, y0: 0, x1: 20, y1: 20, scale });
  const context = () => fakeCanvas().getContext() as unknown as CanvasRenderingContext2D;

  it("non disegna le linee da lontano, e le disegna da vicino", () => {
    // A 2,36 milioni di esagoni, disegnarle sempre sarebbe fermo; e sotto una certa distanza
    // sono comunque piu' sottili del tratto, quindi si leggerebbero come un velo grigio.
    expect(paintHexGrid(context(), 24, view(GRID_ZOOM - 1))).toBe(0);
    expect(paintHexGrid(context(), 24, view(GRID_ZOOM + 6))).toBeGreaterThan(0);
  });

  it("non disegna niente in piedi da lontano", () => {
    // A zoom largo l'inquadratura copre centomila celle, e centomila sagome per fotogramma
    // sono una presentazione. Il colore del terreno la vegetazione ce l'ha gia' dentro.
    expect(paintProps(context(), ground, seedNumber("p"), view(PROP_ZOOM - 1))).toBe(0);
    expect(paintProps(context(), ground, seedNumber("p"), view(PROP_ZOOM + 4))).toBeGreaterThan(0);
  });
});
