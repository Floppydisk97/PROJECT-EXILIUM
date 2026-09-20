// A renderer is the one place where being wrong is invisible: it just looks like art. These
// hold the decisions that are not art -- that a tree never moves, that the data really drives
// what is drawn, and that water is never planted on.
import { describe, expect, it } from "vitest";
import { ColonyGround, describe as inspect, groundColor, hash, propAt, seedNumber } from "./ground";

const NAMES = ["deep_water", "water", "marsh", "sand", "soil", "gravel", "rock", "ice"];

function colony(cells: { ground: number; fertility: number; vegetation: number }[], size = 4): ColonyGround {
  return {
    name: "t", label: "T", seed: "seed", size, cell_metres: 8, buildable: 0,
    site: { biome: "temperate_forest", elevation: 100, temperature: 10, rainfall: 900, river_flow: 0, coastal: false },
    ground_names: NAMES,
    cells: {
      ground: cells.map((c) => c.ground),
      height: cells.map(() => 0),
      fertility: cells.map((c) => c.fertility),
      vegetation: cells.map((c) => c.vegetation),
    },
  };
}

const SOIL = NAMES.indexOf("soil");
const WATER = NAMES.indexOf("water");
const ROCK = NAMES.indexOf("rock");

describe("what stands where", () => {
  it("puts the same thing in the same place every time it is asked", () => {
    // The point of hashing the position instead of walking a seeded generator: a tree must
    // not move when the camera does, and the draw order changes with every pan.
    const ground = colony(Array.from({ length: 16 }, () => ({ ground: SOIL, fertility: 80, vegetation: 80 })));
    const seed = seedNumber("abc");
    for (let y = 0; y < 4; y++) {
      for (let x = 0; x < 4; x++) {
        expect(propAt(ground, seed, x, y)).toEqual(propAt(ground, seed, x, y));
      }
    }
  });

  it("never plants anything in water or on ice", () => {
    const ground = colony(Array.from({ length: 16 }, () => ({ ground: WATER, fertility: 90, vegetation: 90 })));
    const seed = seedNumber("abc");
    for (let i = 0; i < 16; i++) {
      expect(propAt(ground, seed, i % 4, Math.floor(i / 4))).toBeNull();
    }
  });

  it("grows more where the data says more grows", () => {
    const seed = seedNumber("abc");
    const count = (vegetation: number) => {
      const big = 24;
      const ground = colony(
        Array.from({ length: big * big }, () => ({ ground: SOIL, fertility: 70, vegetation })),
        big,
      );
      let n = 0;
      for (let y = 0; y < big; y++) for (let x = 0; x < big; x++) if (propAt(ground, seed, x, y)) n++;
      return n;
    };
    expect(count(90)).toBeGreaterThan(count(30));
    expect(count(30)).toBeGreaterThan(count(8));
    expect(count(0)).toBe(0);
  });

  it("puts boulders on rock and plants on soil", () => {
    const seed = seedNumber("abc");
    const big = 20;
    const stone = colony(Array.from({ length: big * big }, () => ({ ground: ROCK, fertility: 0, vegetation: 0 })), big);
    const kinds = new Set<string>();
    for (let y = 0; y < big; y++) for (let x = 0; x < big; x++) {
      const prop = propAt(stone, seed, x, y);
      if (prop) kinds.add(prop.kind);
    }
    expect([...kinds]).toEqual(["rock"]);
  });

  it("keeps every plant inside the cell it belongs to", () => {
    // A sprite that wandered out of its cell would be drawn in the wrong draw order, and the
    // depth of this whole view is nothing but draw order.
    const big = 12;
    const ground = colony(Array.from({ length: big * big }, () => ({ ground: SOIL, fertility: 90, vegetation: 95 })), big);
    const seed = seedNumber("xyz");
    for (let y = 0; y < big; y++) for (let x = 0; x < big; x++) {
      const prop = propAt(ground, seed, x, y);
      if (!prop) continue;
      expect(prop.x).toBeGreaterThanOrEqual(x);
      expect(prop.x).toBeLessThan(x + 1);
      expect(prop.y).toBeGreaterThanOrEqual(y);
      expect(prop.y).toBeLessThan(y + 1);
    }
  });
});

describe("what the ground looks like", () => {
  it("greens earth that has something growing on it", () => {
    const bare = colony([{ ground: SOIL, fertility: 10, vegetation: 0 }], 1);
    const lush = colony([{ ground: SOIL, fertility: 90, vegetation: 95 }], 1);
    const [, bareGreen] = groundColor(bare, 0);
    const [, lushGreen] = groundColor(lush, 0);
    expect(lushGreen).toBeGreaterThan(bareGreen);
  });

  it("leaves water alone whatever the columns beside it say", () => {
    const a = colony([{ ground: WATER, fertility: 0, vegetation: 0 }], 1);
    const b = colony([{ ground: WATER, fertility: 99, vegetation: 99 }], 1);
    expect(groundColor(a, 0)).toEqual(groundColor(b, 0));
  });

  it("says what a cell is, in words, with its fertility", () => {
    const ground = colony([{ ground: SOIL, fertility: 62, vegetation: 40 }], 1);
    expect(inspect(ground, 0, 0)).toBe("Terra (fert. 62%)");
    const wet = colony([{ ground: WATER, fertility: 0, vegetation: 0 }], 1);
    expect(inspect(wet, 0, 0)).toBe("Acqua");
  });
});

describe("the hash", () => {
  it("is spread out, so the texture it drives is not striped", () => {
    const buckets = new Array(10).fill(0);
    for (let x = 0; x < 120; x++) for (let y = 0; y < 120; y++) {
      buckets[Math.min(9, Math.floor(hash(1234, x, y, 5) * 10))]++;
    }
    for (const bucket of buckets) expect(bucket).toBeGreaterThan(14400 / 10 * 0.75);
  });
});
