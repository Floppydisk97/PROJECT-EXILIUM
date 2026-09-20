// The test that makes two copies of one rule safe.
//
// `citygen.ts` is a port of `backend/app/citygen.py`, and this project has been hurt before by
// two definitions that had to agree and quietly stopped. So the agreement is not assumed: the
// Python side writes `reference.json` -- five sites, every cell -- and this regenerates them
// and compares. A drift of a single cell fails the build.
//
// Regenerate the reference with the snippet in `docs/architecture.md` when the rules change,
// and expect this to fail first if only one side was changed. That failure is the point.
import { describe, expect, it } from "vitest";
import reference from "./reference.json";
import { generate, seedFor } from "./citygen";
import { Prng, seedInt } from "./prng";

describe("the two generators agree", () => {
  for (const testCase of reference.cases) {
    it(`cell for cell on ${testCase.name}`, () => {
      const made = generate(testCase.seed, testCase.site, reference.size);
      expect([...made.cells.ground]).toEqual(testCase.ground);
      expect([...made.cells.height]).toEqual(testCase.height);
      expect([...made.cells.fertility]).toEqual(testCase.fertility);
      expect([...made.cells.vegetation]).toEqual(testCase.vegetation);
      expect(made.buildable).toBe(testCase.buildable);
    });
  }

  it("covers the cases that actually differ", () => {
    // A reference of five identical meadows would pass whatever the code did. Water, ice,
    // rock, a river and a coast are the branches that make the generator interesting.
    const biomes = new Set(reference.cases.map((c) => c.site.biome));
    expect(biomes.size).toBeGreaterThanOrEqual(4);
    expect(reference.cases.some((c) => c.site.river_flow > 0)).toBe(true);
    expect(reference.cases.some((c) => c.site.coastal)).toBe(true);
    expect(reference.cases.some((c) => c.site.temperature < -8)).toBe(true);
  });
});

describe("the generator that both are built on", () => {
  it("produces the numbers the Python twin produces", () => {
    // Pinned against values printed by `python -c` from `app.prng`. Mulberry32 is thirty-two
    // bit integer arithmetic precisely so that this can be true.
    expect(seedInt("prova")).toBe(2042925649);
    const prng = new Prng("prova");
    expect([...Array(5)].map(() => prng.nextUint()))
      .toEqual([1041935993, 290468120, 3660437992, 3639609783, 1645382567]);
    const direction = new Prng("dir").direction();
    expect(direction.map((c) => +c.toFixed(12)))
      .toEqual([-0.860781780089, 0.480693964957, 0.167296261527]);
  });
});

describe("the seed", () => {
  it("belongs to the tile, so a site can be scouted before it is taken", async () => {
    const first = await seedFor("Erebo-01", 1234);
    expect(await seedFor("Erebo-01", 1234)).toBe(first);
    expect(await seedFor("Erebo-01", 1235)).not.toBe(first);
    expect(await seedFor("Altrove", 1234)).not.toBe(first);
    expect(first).toHaveLength(32);
  });
});
