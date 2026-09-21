// Il rilievo e' la parte del disegno dove sbagliare non si vede: viene fuori un terreno un po'
// strano, e un terreno un po' strano sembra una scelta. Queste sono le cose che NON sono
// scelte -- che l'acqua si faccia fonda allontanandosi dalla riva, che la riva si misuri in
// celle, e che il colore del terreno non dipenda da come e' inclinato.
import { describe, expect, it } from "vitest";
import { computeRelief, shoreCells } from "./relief";
import { litColor, type ColonyGround } from "./ground";

const NAMES = ["deep_water", "water", "marsh", "sand", "soil", "gravel", "rock", "ice"];
const SOIL = NAMES.indexOf("soil");
const WATER = NAMES.indexOf("water");

function colony(size: number, at: (x: number, y: number) => { ground: number; height: number }): ColonyGround {
  const ground = new Uint8Array(size * size);
  const height = new Int32Array(size * size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const cell = at(x, y);
      ground[y * size + x] = cell.ground;
      height[y * size + x] = cell.height;
    }
  }
  return {
    seed: "seed", size, cell_metres: 8, buildable: 0,
    economy: { food: 0, timber: 0, stone: 0, ore: 0, wind: 0, sun: 0, water: 0, heat: 0, effort: 0, room: 0 },
    site: { biome: "temperate_forest", elevation: 100, temperature: 10, rainfall: 900, river_flow: 0, coastal: false },
    ground_names: NAMES,
    cells: { ground, height, fertility: new Uint8Array(size * size), vegetation: new Uint8Array(size * size) },
  };
}

describe("il rilievo non ombreggia piu'", () => {
  it("da' lo stesso colore a un fianco ripido e a una piana", () => {
    // La prova che l'ombreggiatura non torna dentro di nascosto. C'era, e su un rilievo fatto
    // di poche armoniche produceva fasce diagonali chiare e scure lunghe tutta la mappa,
    // sempre nella stessa direzione: una pianura a righe. Il colore di una cella adesso
    // dipende da COSA c'e' li' -- terra, verde, acqua -- e non da come e' inclinata.
    const size = 32;
    const flat = colony(size, () => ({ ground: SOIL, height: 140 }));
    const ramp = colony(size, (x) => ({ ground: SOIL, height: x * 90 }));
    const middle = Math.floor(size / 2) * size + Math.floor(size / 2);
    expect(litColor(ramp, computeRelief(ramp), middle))
      .toEqual(litColor(flat, computeRelief(flat), middle));
  });

  it("non tiene in giro la luce che diceva di aver tolto", () => {
    // Una costante a zero lasciata in mezzo al codice e' peggio del difetto che nasconde: il
    // prossimo che passa la rialza per vedere cosa fa. Il campo non esiste proprio.
    const relief = computeRelief(colony(8, () => ({ ground: SOIL, height: 0 })));
    expect(Object.keys(relief).sort()).toEqual(["depth", "shore"]);
  });
});

describe("l'acqua e la riva", () => {
  const size = 32;
  // Meta' acqua, che si fa fonda allontanandosi dalla riva a meta' mappa.
  const bay = computeRelief(colony(size, (x) => (
    x < 16 ? { ground: WATER, height: -(16 - x) * 30 } : { ground: SOIL, height: (x - 16) * 4 }
  )));

  it("fa fonda l'acqua lontano da terra, e lascia la terra asciutta", () => {
    expect(bay.depth[10 * size + 0]).toBeGreaterThan(bay.depth[10 * size + 14]);
    expect(bay.depth[10 * size + 20]).toBe(0);
  });

  it("misura la riva in celle, e non oltre la sua portata", () => {
    // Una DISTANZA, non una comodita' gia' invertita: la schiuma la vuole corta, l'orlo
    // bagnato cortissima, e le due misure escono dalla stessa passata solo cosi'.
    expect(shoreCells(bay, 10 * size + 15)).toBe(0);
    expect(shoreCells(bay, 10 * size + 16)).toBe(0);
    expect(shoreCells(bay, 10 * size + 18)).toBeCloseTo(2, 5);
    expect(shoreCells(bay, 10 * size + 31)).toBeGreaterThanOrEqual(7);
  });
});
