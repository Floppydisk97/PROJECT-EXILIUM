// The twin of `backend/app/citygen.py`, line for line.
//
// Two copies of one rule is how this project has been hurt before, so the copy is not trusted:
// `citygen.test.ts` regenerates several sites and compares every cell against a reference the
// Python side wrote, and a drift of one cell fails the build. The generator was deliberately
// rewritten to make that possible -- no language's own random generator, no logarithms in the
// direction sampling -- because the alternative was reimplementing CPython's Mersenne Twister
// in JavaScript and keeping it right for ever.
//
// Why a copy at all: the planet viewer is a static site with no API in front of it, and asking
// a server what the ground looks like would put a sleeping instance back on the path of simply
// looking at the world. The SERVER stays the authority for anything that is decided -- what is
// built, who owns what. This copy is for looking.
import { Prng } from "./prng";

export const SIZE = 768;          // cells a side: ~590k cells, about six kilometres across
export const CELL_METRES = 8;

export const GROUNDS = [
  "deep_water", "water", "marsh", "sand", "soil", "gravel", "rock", "ice",
] as const;

/** Quanto la costa si scosta dalla sua retta, in unita' di mezza mappa: una ventina di
 *  celle, cioe' una baia e non un frattale. */
export const COAST_WANDER = 0.055;

export const RIPARIAN_REACH = 260.0;
export const RIPARIAN_GAIN = 55;
export const POOLING_CLIMATE = 0.40;
export const RIPARIAN_COVER = 0.78;
export const ALLUVIUM_REACH = 150.0;

// Nessun posto e' del tutto morto -- gemelle di `citygen.OASIS_*`. Una casella senza niente da
// raccogliere non e' un sito difficile, e' un sito che non si puo' giocare, e il deserto e la
// roccia nuda erano esattamente quello. A macchie e non uniforme di proposito: un deserto con
// un velo di verde dappertutto non e' un deserto, e' una steppa.
export const OASIS_FERTILITY_FLOOR = 12;
export const OASIS_FERTILITY_PEAK = 20;
export const OASIS_COVER_FLOOR = 0.18;
export const OASIS_COVER_PEAK = 0.40;
export const OASIS_BREAKS_ROCK = 0.55;

export type BiomeRule = {
  ground: string; fertility: number; cover: number; roughness: number; wet: number;
};

export const BIOME_RULES: Record<string, BiomeRule> = {
  ice_sheet:           { ground: "ice",    fertility: 0,  cover: 0.00, roughness: 0.35, wet: 0.10 },
  snow_cap:            { ground: "ice",    fertility: 0,  cover: 0.00, roughness: 1.40, wet: 0.05 },
  bare_rock:           { ground: "rock",   fertility: 4,  cover: 0.02, roughness: 1.30, wet: 0.05 },
  tundra:              { ground: "gravel", fertility: 18, cover: 0.12, roughness: 0.55, wet: 0.35 },
  boreal_forest:       { ground: "soil",   fertility: 42, cover: 0.72, roughness: 0.70, wet: 0.30 },
  temperate_forest:    { ground: "soil",   fertility: 68, cover: 0.80, roughness: 0.60, wet: 0.25 },
  temperate_swamp:     { ground: "marsh",  fertility: 74, cover: 0.55, roughness: 0.20, wet: 0.85 },
  arid_shrubland:      { ground: "gravel", fertility: 28, cover: 0.22, roughness: 0.65, wet: 0.10 },
  desert:              { ground: "sand",   fertility: 8,  cover: 0.04, roughness: 0.45, wet: 0.02 },
  tropical_rainforest: { ground: "soil",   fertility: 88, cover: 0.95, roughness: 0.75, wet: 0.45 },
  tropical_swamp:      { ground: "marsh",  fertility: 82, cover: 0.70, roughness: 0.20, wet: 0.90 },
};
export const DEFAULT_RULE: BiomeRule =
  { ground: "soil", fertility: 40, cover: 0.40, roughness: 0.60, wet: 0.30 };

export type Site = {
  biome: string; elevation: number; temperature: number;
  rainfall: number; river_flow: number; coastal: boolean;
};
// `river_flow` e' la portata di un fiume che attraversa DAVVERO questa casella, zero se non ce
// n'e' nessuno -- e non e' lo stesso numero che il pianeta memorizza. L'accumulo di deflusso da'
// a ogni casella di terra almeno la sua pioggia, quindi `river_flow` grezzo e' sopra zero quasi
// ovunque: copiato cosi', disegnava un fiume in mezzo a OGNI colonia del pianeta, ed e' quello
// che ha fatto finche' nessuno e' sceso a guardare. Chi costruisce un Site confronta la portata
// con `map.river_min_flow`, la stessa soglia su cui il globo disegna i suoi fiumi, e passa zero
// quando non la raggiunge.

export type Cells = {
  ground: Uint8Array; height: Int32Array; fertility: Uint8Array; vegetation: Uint8Array;
};

function clamp100(value: number): number {
  return Math.trunc(Math.max(0, Math.min(100, value)));
}

function smoothstep(t: number): number {
  const c = t < 0 ? 0 : t > 1 ? 1 : t;
  return c * c * (3 - 2 * c);
}

/** Band-limited noise on a plane: seeded directions, frequencies and phases. */
class PlaneNoise {
  private terms: [number, number, number, number, number][] = [];   // dx, dy, freq, phase, amp
  private total = 0;

  constructor(rng: Prng, octaves: number, baseFreq: number) {
    let amp = 1.0;
    let freq = baseFreq;
    for (let i = 0; i < octaves; i++) {
      const [dx, dy] = rng.direction();
      this.terms.push([dx, dy, freq, rng.uniform(0, 2 * Math.PI), amp]);
      this.total += amp;
      amp *= 0.55;
      freq *= 1.9;
    }
  }

  at(x: number, y: number): number {
    let value = 0;
    for (const [dx, dy, freq, phase, amp] of this.terms) {
      value += amp * Math.sin(freq * (dx * x + dy * y) + phase);
    }
    return value / this.total;
  }
}

/** The seed a tile's ground grows from. The TILE decides, not whoever lands on it, so a site
 *  can be scouted before it is taken. Mirrors `citygen.seed_for`, which is sha256 -- done here
 *  with the Web Crypto API because a hash is the one thing worth taking from the platform. */
export async function seedFor(worldSeed: string, tileId: number): Promise<string> {
  const bytes = new TextEncoder().encode(`${worldSeed}:${tileId}`);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

/** What the ground is worth, as three integers -- the twin of `citygen.SiteEconomy`.
 *
 *  Computed here as well as on the server so a site can be WEIGHED before it is taken. The
 *  server writes its own copy down at landing and never asks this one; this is what turns
 *  "scendi sul terreno" from a picture into a decision. */
export type SiteEconomy = {
  food: number;      // fertility of the buildable land
  timber: number;    // standing growth alone -- a bog has none
  stone: number;     // share of the map that is rock or gravel
  ore: number;       // share carrying a vein -- the only one that is not on the surface
  wind: number;      // quanto tira: creste e coste
  sun: number;       // quanto splende: cieli sgombri e caldo
  water: number;     // quanto scorre: la portata del fiume
  heat: number;      // quanto scotta sotto: geologia nascosta, come i filoni
  effort: number;    // growth AND marsh to clear
  room: number;      // buildable cells
};

export type Generated = {
  seed: string; size: number; cell_metres: number; site: Site;
  ground_names: string[]; cells: Cells; buildable: number; economy: SiteEconomy;
};

/** The colony's ground, from a seed and what the planet said about the site. */
export function generate(seed: string, site: Site, size: number = SIZE): Generated {
  const rule = BIOME_RULES[site.biome] ?? DEFAULT_RULE;

  const relief = new PlaneNoise(new Prng(`${seed}:relief`), 5, 3.2);
  const detail = new PlaneNoise(new Prng(`${seed}:detail`), 3, 11.0);
  const damp = new PlaneNoise(new Prng(`${seed}:damp`), 4, 4.5);
  const grain = new PlaneNoise(new Prng(`${seed}:grain`), 3, 9.0);
  // I filoni: un campo tutto suo, a frequenza alta perche' un giacimento e' stretto. Se
  // seguisse la pietra di superficie non aggiungerebbe nessuna geografia.
  const veins = new PlaneNoise(new Prng(`${seed}:veins`), 3, 13.0);
  // Il calore sta piu' in profondita' dei filoni, quindi il suo campo e' piu' largo: un
  // giacimento e' una vena, un'anomalia termica e' una regione.
  const deep = new PlaneNoise(new Prng(`${seed}:deep`), 3, 7.0);
  // La costa serpeggia. Senza, e' una diagonale tirata col righello: a sei chilometri
  // non si legge come una costa, si legge come la sponda di un canale.
  const coast = new PlaneNoise(new Prng(`${seed}:coast`), 3, 5.5);
  // Le macchie fertili: campo LARGO, perche' cio' che deve produrre e' un'oasi -- una manciata
  // di posti buoni che si vedono da lontano -- non della polvere verde sparsa.
  const oasis = new PlaneNoise(new Prng(`${seed}:oasis`), 3, 2.6);

  const altitudeRoughness = 0.6 + Math.min(2.0, Math.max(0, site.elevation) / 2200.0);
  const amplitude = 320.0 * rule.roughness * altitudeRoughness;

  // Where bare rock starts. A flat 0.62 of the relief handed EVERY biome the same 16 per cent
  // of naked stone -- a rainforest with continents of grey in it. What covers rock is
  // vegetation, and the biome already says how much it has.
  const bareAbove = amplitude * (0.62 + 0.30 * rule.cover);
  // Piu' in alto, piu' facile incontrare un filone: la roccia profonda viene a giorno dove
  // la crosta e' stata spinta su.
  const veinLine = 0.62 - 0.30 * Math.min(1, Math.max(0, site.elevation) / 2500.0);
  const heatLine = 0.30 - 0.20 * Math.min(1, Math.max(0, site.elevation) / 2500.0);

  const hasRiver = site.river_flow > 0;
  const riverAxis = new Prng(`${seed}:river`).uniform(0, Math.PI);
  const riverWidth = 3.0 + 9.0 * smoothstep(Math.log10(Math.max(1, site.river_flow)) / 3.0);
  const shoreAngle = new Prng(`${seed}:shore`).uniform(0, 2 * Math.PI);
  const shoreDx = Math.cos(shoreAngle);
  const shoreDy = Math.sin(shoreAngle);
  const riverCos = Math.cos(riverAxis);
  const riverSin = Math.sin(riverAxis);

  const wetness = rule.wet + Math.min(0.35, site.rainfall / 6000.0);
  const warmth = smoothstep((site.temperature + 15.0) / 45.0);
  const fertilityBase = rule.fertility * (0.55 + 0.75 * Math.min(1, site.rainfall / 1800.0));
  const frozen = site.temperature < -8.0;

  const cells: Cells = {
    ground: new Uint8Array(size * size),
    height: new Int32Array(size * size),
    fertility: new Uint8Array(size * size),
    vegetation: new Uint8Array(size * size),
  };
  const iWater = GROUNDS.indexOf("water");
  const iDeep = GROUNDS.indexOf("deep_water");
  const iMarsh = GROUNDS.indexOf("marsh");
  const iIce = GROUNDS.indexOf("ice");
  const iRock = GROUNDS.indexOf("rock");
  const iSand = GROUNDS.indexOf("sand");
  const poolFloor = amplitude * (0.90 - 0.65 * Math.min(1, wetness));
  const iSoil = GROUNDS.indexOf("soil");
  const iGravel = GROUNDS.indexOf("gravel");
  let buildable = 0;
  let usableFertility = 0;
  let greenery = 0;
  let marshCells = 0;
  let stoneCells = 0;
  let oreCells = 0;
  let heatCells = 0;

  for (let y = 0; y < size; y++) {
    const v = (y / (size - 1)) * 2 - 1;
    for (let x = 0; x < size; x++) {
      const u = (x / (size - 1)) * 2 - 1;
      const at = y * size + x;
      let metres = (relief.at(u, v) + 0.35 * detail.at(u, v)) * amplitude;

      let bank = -1e9;
      let depthBelow = 0;
      if (site.coastal) {
        const towardSea = u * shoreDx + v * shoreDy + COAST_WANDER * coast.at(u, v);
        const shoreTerm = (towardSea - 0.35) * 900.0;
        if (shoreTerm > depthBelow) depthBelow = shoreTerm;
        if (shoreTerm > bank) bank = shoreTerm;
      }
      if (hasRiver) {
        const across = (u * riverCos + v * riverSin) * 100.0 + 14.0 * damp.at(u, v);
        const riverTerm = (riverWidth - Math.abs(across)) * 26.0;
        if (riverTerm > depthBelow) depthBelow = riverTerm;
        if (riverTerm > bank) bank = riverTerm;
      }
      const poolTerm = (-metres - poolFloor) * (0.6 + wetness);
      if (poolTerm > depthBelow) depthBelow = poolTerm;
      if (wetness > POOLING_CLIMATE && poolTerm > bank) bank = poolTerm;

      if (depthBelow > 0) {
        metres -= depthBelow;
        cells.ground[at] = frozen ? iIce : depthBelow > 260 ? iDeep : iWater;
        cells.height[at] = Math.trunc(metres);
        continue;             // fertility and vegetation stay zero
      }

      let name = rule.ground;
      if (frozen) name = "ice";
      else if (metres > bareAbove && rule.ground !== "sand") name = "rock";
      else if (metres < -amplitude * 0.30 && wetness > 0.55) name = "marsh";
      else if (rule.ground === "soil" && grain.at(u, v) > 0.55) name = "gravel";
      // Quanto questa cella sta dentro una macchia fertile: 0 fuori, 1 nel cuore.
      const patch = smoothstep((oasis.at(u, v) - 0.05) * 2.4);
      // La macchia rompe la lastra: pietraia con la terra fra i sassi invece di roccia viva,
      // e su una pietraia qualcosa cresce. Vale anche in cresta, e non toglie niente alla
      // montagna -- la pietraia conta come pietra esattamente come la roccia.
      if (name === "rock" && patch > OASIS_BREAKS_ROCK) name = "gravel";
      if ((name === "sand" || name === "gravel") && bank > -ALLUVIUM_REACH && !frozen) {
        name = "soil";
      }

      const index = GROUNDS.indexOf(name as (typeof GROUNDS)[number]);
      const slopePenalty = 1 - smoothstep(Math.abs(metres) / Math.max(1, amplitude)) * 0.45;
      const riparian = smoothstep(1 + bank / RIPARIAN_REACH);
      let fertility = 0;
      if (index !== iIce && index !== iRock) {
        fertility = Math.trunc(fertilityBase * slopePenalty * (0.6 + 0.6 * warmth));
        fertility += Math.trunc(RIPARIAN_GAIN * riparian * (0.4 + 0.6 * warmth));
        if (index === iMarsh) fertility = Math.trunc(fertility * 1.15);
        if (index === iSand) fertility = Math.trunc(fertility * 0.45);
        // Il fondo, DOPO le penalita': una duna resta una duna, ma non e' sterile.
        fertility = Math.max(
          fertility, Math.trunc(OASIS_FERTILITY_FLOOR + OASIS_FERTILITY_PEAK * patch));
      }
      fertility = Math.max(0, Math.min(100, fertility));

      let cover = rule.cover + (RIPARIAN_COVER - rule.cover) * riparian;
      cover *= 0.5 + 0.5 * (0.5 + 0.5 * grain.at(u, v));
      // E il fondo anche qui: se no la fertilita' minima restava un numero che nessuno vedeva,
      // cioe' terra buona e pelata.
      cover = Math.max(cover, OASIS_COVER_FLOOR + OASIS_COVER_PEAK * patch);
      let vegetation = 0;
      if (fertility > 0) {
        vegetation = Math.max(0, Math.min(100,
          Math.trunc(100 * cover * Math.sqrt(fertility / 100))));
      }

      if (veins.at(u, v) > veinLine) oreCells++;
      if (deep.at(u, v) > heatLine) heatCells++;

      cells.ground[at] = index;
      cells.height[at] = Math.trunc(metres);
      cells.fertility[at] = fertility;
      cells.vegetation[at] = vegetation;
      if (index === iSand || index === iSoil || index === iGravel || index === iRock) {
        buildable++;
        usableFertility += fertility;      // yield is the quality of what you can build on
      }
      greenery += vegetation;
      if (index === iMarsh) marshCells++;
      if (index === iRock || index === iGravel) stoneCells++;
    }
  }

  // The three numbers the economy keeps instead of the map. Mirrors `CityMap.economy`:
  // yield is the fertility of the BUILDABLE land -- averaged over everything, a swamp full
  // of water reads as middling, which confuses "excellent ground" with "ground you can use".
  const cells_total = size * size;
  const greenAverage = Math.trunc(greenery / cells_total);
  const economy: SiteEconomy = {
    food: buildable ? Math.trunc(usableFertility / buildable) : 0,
    timber: greenAverage,
    stone: Math.trunc((100 * stoneCells) / cells_total),
    ore: Math.trunc((100 * oreCells) / cells_total),
    // Le quattro attitudini energetiche. Tre si leggono da cio' che il pianeta gia' diceva;
    // il calore no, e' geologia nascosta. Gemelle di `citygen.energy_potentials`.
    wind: clamp100(18 + Math.max(0, site.elevation) / 28.0 + (site.coastal ? 28 : 0)),
    sun: clamp100(96 - site.rainfall / 24.0 + (site.temperature - 10) / 1.8),
    water: clamp100(site.river_flow / 34.0),
    heat: Math.trunc((100 * heatCells) / cells_total),
    effort: greenAverage + Math.trunc((100 * marshCells) / cells_total),
    room: buildable,
  };

  return {
    seed, size, cell_metres: CELL_METRES, site,
    ground_names: [...GROUNDS], cells, buildable, economy,
  };
}
