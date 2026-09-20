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

export const RIPARIAN_REACH = 260.0;
export const RIPARIAN_GAIN = 55;
export const POOLING_CLIMATE = 0.40;
export const RIPARIAN_COVER = 0.78;
export const ALLUVIUM_REACH = 150.0;

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

export type Cells = {
  ground: Uint8Array; height: Int32Array; fertility: Uint8Array; vegetation: Uint8Array;
};

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

export type Generated = {
  seed: string; size: number; cell_metres: number; site: Site;
  ground_names: string[]; cells: Cells; buildable: number;
};

/** The colony's ground, from a seed and what the planet said about the site. */
export function generate(seed: string, site: Site, size: number = SIZE): Generated {
  const rule = BIOME_RULES[site.biome] ?? DEFAULT_RULE;

  const relief = new PlaneNoise(new Prng(`${seed}:relief`), 5, 3.2);
  const detail = new PlaneNoise(new Prng(`${seed}:detail`), 3, 11.0);
  const damp = new PlaneNoise(new Prng(`${seed}:damp`), 4, 4.5);
  const grain = new PlaneNoise(new Prng(`${seed}:grain`), 3, 9.0);

  const altitudeRoughness = 0.6 + Math.min(2.0, Math.max(0, site.elevation) / 2200.0);
  const amplitude = 320.0 * rule.roughness * altitudeRoughness;

  // Where bare rock starts. A flat 0.62 of the relief handed EVERY biome the same 16 per cent
  // of naked stone -- a rainforest with continents of grey in it. What covers rock is
  // vegetation, and the biome already says how much it has.
  const bareAbove = amplitude * (0.62 + 0.30 * rule.cover);

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
  let buildable = 0;

  for (let y = 0; y < size; y++) {
    const v = (y / (size - 1)) * 2 - 1;
    for (let x = 0; x < size; x++) {
      const u = (x / (size - 1)) * 2 - 1;
      const at = y * size + x;
      let metres = (relief.at(u, v) + 0.35 * detail.at(u, v)) * amplitude;

      let bank = -1e9;
      let depthBelow = 0;
      if (site.coastal) {
        const shoreTerm = (u * shoreDx + v * shoreDy - 0.35) * 900.0;
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
      }
      fertility = Math.max(0, Math.min(100, fertility));

      let cover = rule.cover + (RIPARIAN_COVER - rule.cover) * riparian;
      cover *= 0.5 + 0.5 * (0.5 + 0.5 * grain.at(u, v));
      let vegetation = 0;
      if (fertility > 0) {
        vegetation = Math.max(0, Math.min(100,
          Math.trunc(100 * cover * Math.sqrt(fertility / 100))));
      }

      cells.ground[at] = index;
      cells.height[at] = Math.trunc(metres);
      cells.fertility[at] = fertility;
      cells.vegetation[at] = vegetation;
      if (index === iSand || index === GROUNDS.indexOf("soil")
          || index === GROUNDS.indexOf("gravel") || index === iRock) buildable++;
    }
  }

  return {
    seed, size, cell_metres: CELL_METRES, site,
    ground_names: [...GROUNDS], cells, buildable,
  };
}
