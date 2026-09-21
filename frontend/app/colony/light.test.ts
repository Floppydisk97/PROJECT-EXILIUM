// La luce e' la parte del disegno dove sbagliare non si vede: viene fuori un terreno un po'
// strano, e un terreno un po' strano sembra una scelta. Queste sono le cose che NON sono
// scelte -- che il piano resti piano, che il sole venga da una parte sola, che l'acqua si
// faccia fonda allontanandosi dalla riva.
import { describe, expect, it } from "vitest";
import { computeRelief, lightOf, shoreCells } from "./light";
import type { ColonyGround } from "./ground";

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

const middle = (size: number) => Math.floor(size / 2) * size + Math.floor(size / 2);

describe("il rilievo", () => {
  it("lascia il piano esattamente com'era", () => {
    // Il numero che conta e' 1 e non "circa 1": e' cio' che garantisce che la tavolozza si
    // veda com'e' stata scelta dove il terreno non fa niente.
    const flat = computeRelief(colony(32, () => ({ ground: SOIL, height: 140 })));
    for (let i = 0; i < 32 * 32; i++) expect(lightOf(flat, i)).toBe(1);
  });

  it("accende il fianco rivolto al sole e spegne l'altro", () => {
    // Il sole sta in alto a sinistra, come l'ombra sotto gli alberi. Un fianco che sale verso
    // destra guarda a sinistra, quindi prende luce; quello che scende e' in ombra.
    const size = 48;
    const up = computeRelief(colony(size, (x) => ({ ground: SOIL, height: x * 6 })));
    const down = computeRelief(colony(size, (x) => ({ ground: SOIL, height: -x * 6 })));
    // Il verso, non la quantita': su una rampa uniforme ogni cella e' inclinata come tutte
    // le altre, e la scala si tara sul sito -- quindi il rilievo resta giustamente mite.
    expect(lightOf(up, middle(size))).toBeGreaterThan(1.05);
    expect(lightOf(down, middle(size))).toBeLessThan(0.95);
  });

  it("misura la pendenza sul sito, non su una costante", () => {
    // Una piana e una valle alpina hanno lo stesso diritto di vedersi: se la scala fosse
    // assoluta, una sarebbe carta bianca e l'altra carbone.
    const size = 48;
    const gentle = computeRelief(colony(size, (x) => ({ ground: SOIL, height: Math.round(x * 0.4) })));
    const alpine = computeRelief(colony(size, (x) => ({ ground: SOIL, height: x * 90 })));
    expect(lightOf(gentle, middle(size))).toBeGreaterThan(1.05);
    expect(Math.abs(lightOf(gentle, middle(size)) - lightOf(alpine, middle(size)))).toBeLessThan(0.25);
  });

  it("non stampa le curve di livello sulla sabbia", () => {
    // Le altezze sono interi di metri: derivare una scala a gradini dava terrazze, e le
    // terrazze si vedevano come un'impronta digitale su tutta la piana.
    const size = 64;
    const dune = computeRelief(colony(size, (x, y) => ({
      ground: SOIL, height: Math.trunc(30 * Math.sin(x / 9) + 30 * Math.sin(y / 11)),
    })));
    let jumps = 0;
    for (let y = 1; y < size - 1; y++) {
      for (let x = 2; x < size - 2; x++) {
        const i = y * size + x;
        if (Math.abs(lightOf(dune, i) - lightOf(dune, i - 1)) > 0.08) jumps++;
      }
    }
    expect(jumps).toBe(0);
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
