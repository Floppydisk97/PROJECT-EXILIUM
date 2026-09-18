// The geometry builders are the part of the client that can be wrong without anything
// complaining: the type checker sees arrays of numbers, and a screenshot only shows the
// frame someone happened to look at. These tests check the arithmetic directly.
import { describe, expect, it } from "vitest";
import {
  buildCliffs, buildRivers, buildSteps, buildTerrain, ICE, SEA, SHELF, relief, tileAt,
  tileRadius,
} from "./terrain";
import { RIVER_MAJOR, RIVER_MINOR, type WorldMap } from "./biomes";

const BIOMES = ["ocean", "lake", "sea_ice", "ice_sheet", "snow_cap", "bare_rock", "tundra",
  "boreal_forest", "temperate_forest", "temperate_swamp", "arid_shrubland", "desert",
  "tropical_rainforest", "tropical_swamp"];

const biome = (name: string) => BIOMES.indexOf(name);

type TileSpec = {
  ring: number[];
  elevation: number;
  biome: string;
  center?: [number, number, number];
  normal?: [number, number, number];
  river_flow?: number;
};

/** A hand-built render model in the shape the backend sends. Four corners is enough to put
 *  two cells side by side and see which of their edges the coastline picks up. */
function world(tiles: TileSpec[], corners: number[], rivers: Partial<WorldMap["rivers"]> = {}): WorldMap {
  const ring: number[] = [];
  const ring_offset = [0];
  for (const t of tiles) {
    ring.push(...t.ring);
    ring_offset.push(ring.length);
  }
  const unit = (i: number): [number, number, number] => {
    const a = (i + 1) * 0.7;
    const v: [number, number, number] = [Math.cos(a), Math.sin(a), 0.2 * i];
    const n = Math.hypot(...v);
    return [v[0] / n, v[1] / n, v[2] / n];
  };
  return {
    name: "Test", seed: "test", frequency: 20, sea_level: 0,
    tile_count: tiles.length, land_count: tiles.filter((t) => t.elevation >= 0).length,
    elevation_max: 7000, relief_gain: 0.075, river_min_flow: 20,
    biome_names: BIOMES,
    corners,
    tiles: {
      id: tiles.map((_, i) => i),
      center: tiles.flatMap((t, i) => t.center ?? unit(i)),
      normal: tiles.flatMap((t, i) => t.normal ?? t.center ?? unit(i)),
      elevation: tiles.map((t) => t.elevation),
      temperature: tiles.map(() => 10),
      rainfall: tiles.map(() => 800),
      biome: tiles.map((t) => biome(t.biome)),
      river_flow: tiles.map((t) => t.river_flow ?? 0),
      landmass_size: tiles.map(() => 2),
      neighbor_count: tiles.map((t) => t.ring.length),
      ring, ring_offset,
    },
    rivers: { a: [], b: [], flow: [], ae: [], be: [], ...rivers },
  };
}

// Four corners; tiles 0 and 1 share the edge (0,1).
const CORNERS = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, -1];
const twoLand = () => world([
  { ring: [0, 1, 2], elevation: 500, biome: "temperate_forest" },
  { ring: [1, 0, 3], elevation: 700, biome: "temperate_forest" },
], CORNERS);

describe("buildTerrain", () => {
  it("fills every buffer exactly, one triangle per ring edge", () => {
    const map = twoLand();
    const built = buildTerrain(map);
    const triangles = map.tiles.ring.length;

    expect(built.positions).toHaveLength(triangles * 9);
    expect(built.colors).toHaveLength(triangles * 9);
    expect(built.grains).toHaveLength(triangles * 3);
    expect(built.faceTile).toHaveLength(triangles);
    // Nothing is left unwritten: a cursor that stopped short would leave vertices at the
    // origin, which render as a spike through the centre of the planet. Every real vertex
    // sits near the unit sphere, so the origin is unmistakable.
    for (let v = 0; v < built.positions.length; v += 3) {
      const radius = Math.hypot(built.positions[v], built.positions[v + 1], built.positions[v + 2]);
      expect(radius).toBeGreaterThan(0.9);
    }
    expect(Array.from(built.grains).every((g) => g > 0)).toBe(true);
  });

  it("maps every triangle back to the tile whose ring produced it", () => {
    const map = twoLand();
    const { faceTile } = buildTerrain(map);
    for (let t = 0; t < map.tiles.id.length; t++) {
      const from = map.tiles.ring_offset[t];
      const to = map.tiles.ring_offset[t + 1];
      for (let f = from; f < to; f++) expect(faceTile[f]).toBe(t);
    }
  });

  it("calls an edge a shoreline only when a single land tile owns it", () => {
    const built = buildTerrain(twoLand());
    // Six ring edges in total, two of which are the same shared edge: four are coast.
    expect(built.coast).toHaveLength(4 * 2);
    const cornerCount = CORNERS.length / 3;
    const pairs = new Set<string>();
    for (let i = 0; i < built.coast.length; i += 2) {
      const key = built.coast[i];
      pairs.add([Math.floor(key / cornerCount), key % cornerCount].join("-"));
    }
    expect(pairs).toEqual(new Set(["1-2", "0-2", "0-3", "1-3"]));
    expect(pairs.has("0-1")).toBe(false);   // the shared edge is inland
  });

  it("outlines dry ground only, never water", () => {
    const map = world([
      { ring: [0, 1, 2], elevation: 500, biome: "temperate_forest" },
      { ring: [1, 0, 3], elevation: -200, biome: "ocean" },
      { ring: [2, 3, 0], elevation: 0, biome: "lake" },
    ], CORNERS);
    // Only the forest tile's three edges get an outline: the sea has no parcels, and a
    // lake is water even though it sits at or above sea level.
    expect(buildTerrain(map).borders).toHaveLength(3 * 6);
  });

  // The regression this suite exists for: when the shading normal was computed only in the
  // land branch, every sea-ice tile came out at one fixed brightness and the polar caps
  // turned into flat plates with a seam along the shore.
  it("hillshades sea ice, not just land", () => {
    const facing: [number, number, number] = [0.52, -0.55, 0.65];
    const away: [number, number, number] = [-0.52, 0.55, -0.65];
    const map = world([
      { ring: [0, 1, 2], elevation: -50, biome: "sea_ice", center: facing, normal: facing },
      { ring: [1, 0, 3], elevation: -50, biome: "sea_ice", center: away, normal: away },
    ], CORNERS);
    const { colors } = buildTerrain(map);
    const lit = colors[0];
    const shadowed = colors[3 * 9];
    expect(lit).toBeGreaterThan(shadowed);
  });
});

describe("tile geometry", () => {
  it("puts each tile on the layer it belongs to", () => {
    const map = world([
      { ring: [0, 1, 2], elevation: 7000, biome: "snow_cap" },
      { ring: [1, 0, 3], elevation: -50, biome: "sea_ice" },
      { ring: [2, 3, 0], elevation: -400, biome: "ocean" },
    ], CORNERS);
    expect(tileRadius(map, 0)).toBeCloseTo(1 + map.relief_gain, 6);   // full relief
    expect(tileRadius(map, 1)).toBe(ICE);
    expect(tileRadius(map, 2)).toBe(SHELF);
    // Water layers stack in the order the cliffs assume: the shell is under everything.
    expect(SEA).toBeLessThan(SHELF);
    expect(SHELF).toBeLessThan(ICE);
    expect(ICE).toBeLessThan(1);
  });

  it("clamps relief at the ceiling the server declared", () => {
    const map = twoLand();
    expect(relief(map, -3000)).toBe(1);                       // underwater is not sunken
    expect(relief(map, map.elevation_max * 2)).toBeCloseTo(1 + map.relief_gain, 6);
  });

  it("derives latitude and longitude from the centre vector", () => {
    const map = world([{ ring: [0, 1, 2], elevation: 10, biome: "desert", center: [0, 0, 1] }], CORNERS);
    expect(tileAt(map, 0).lat).toBeCloseTo(90, 6);
    const equator = world([{ ring: [0, 1, 2], elevation: 10, biome: "desert", center: [0, 1, 0] }], CORNERS);
    expect(tileAt(equator, 0).lat).toBeCloseTo(0, 6);
    expect(tileAt(equator, 0).lon).toBeCloseTo(90, 6);
  });
});

describe("buildCliffs", () => {
  it("drops a wall from the shoreline to the open-ocean shell", () => {
    const map = twoLand();
    const built = buildTerrain(map);
    const cliffs = buildCliffs(map, built.coast);
    const edges = built.coast.length / 2;
    expect(cliffs.positions).toHaveLength(edges * 18);   // two triangles per edge
    expect(cliffs.lines).toHaveLength(edges * 6);        // one segment along the top

    // Every wall spans from its tile's own ground down to the water, and no further.
    for (let i = 0; i < edges; i++) {
      const radii: number[] = [];
      for (let v = 0; v < 6; v++) {
        const o = i * 18 + v * 3;
        radii.push(Math.hypot(cliffs.positions[o], cliffs.positions[o + 1], cliffs.positions[o + 2]));
      }
      expect(Math.min(...radii)).toBeCloseTo(SEA, 6);
      expect(Math.max(...radii)).toBeGreaterThan(1);
    }
  });
});

describe("buildRivers", () => {
  const reach = (flow: number) => ({
    a: [1, 0, 0], b: [0.9950, 0.0998, 0], flow: [flow], ae: [400], be: [100],
  });

  const widthOf = (map: WorldMap) => {
    const { positions, reaches } = buildRivers(map, RIVER_MINOR, RIVER_MAJOR);
    expect(reaches).toBe(1);
    // The first two vertices are the two sides of the upstream end of the ribbon.
    return Math.hypot(
      positions[0] - positions[3], positions[1] - positions[4], positions[2] - positions[5],
    );
  };

  it("widens a river in proportion to what it carries", () => {
    const trickle = world([], CORNERS, reach(20));
    const trunk = world([], CORNERS, reach(400));
    expect(widthOf(trunk)).toBeGreaterThan(widthOf(trickle) * 2);
  });

  it("scales widths with the tiling, so they stay in proportion", () => {
    const coarse = world([], CORNERS, reach(100));
    const fine = { ...world([], CORNERS, reach(100)), frequency: 80 };
    // Four times the frequency, a quarter of the tile, a quarter of the river.
    expect(widthOf(fine)).toBeCloseTo(widthOf(coarse) / 4, 6);
  });

  it("skips a reach that goes nowhere instead of emitting a degenerate ribbon", () => {
    const stuck = world([], CORNERS, {
      a: [1, 0, 0], b: [1, 0, 0], flow: [50], ae: [100], be: [100],
    });
    expect(buildRivers(stuck, RIVER_MINOR, RIVER_MAJOR).reaches).toBe(0);
  });
});

describe("buildSteps", () => {
  const stepped = (low: number, high: number) => world([
    { ring: [0, 1, 2], elevation: low, biome: "temperate_forest" },
    { ring: [1, 0, 3], elevation: high, biome: "bare_rock" },
  ], CORNERS);

  // The defect these exist for: every tile is a flat plate at its own radius, so a height
  // step between neighbours leaves a slit with nothing behind it but the ocean shell. From
  // straight above it is invisible; at a glancing angle the land breaks into loose hexagons
  // with blue showing through.
  it("walls an inner edge once the step is worth seeing", () => {
    const built = buildTerrain(stepped(100, 5000));
    expect(built.steps).toHaveLength(3);          // one edge: key, higher tile, lower tile
    expect(built.steps[1]).toBe(1);               // the 5000 m tile is the higher one
    expect(built.steps[2]).toBe(0);
  });

  it("leaves a step under a pixel open rather than paying for it", () => {
    expect(buildTerrain(stepped(500, 520)).steps).toHaveLength(0);
  });

  it("spans exactly from the higher ground to its neighbour, and no further", () => {
    const map = stepped(100, 5000);
    const built = buildTerrain(map);
    const walls = buildSteps(map, built.steps);
    expect(walls.positions).toHaveLength(18);     // two triangles for the one edge
    expect(walls.lines).toHaveLength(0);          // a fold in the ground is not a shoreline

    const radii: number[] = [];
    for (let v = 0; v < 18; v += 3) {
      radii.push(Math.hypot(walls.positions[v], walls.positions[v + 1], walls.positions[v + 2]));
    }
    expect(Math.max(...radii)).toBeCloseTo(tileRadius(map, 1), 6);
    expect(Math.min(...radii)).toBeCloseTo(tileRadius(map, 0), 6);
    // A wall that ran to the sea would poke out from under the lower tile.
    expect(Math.min(...radii)).toBeGreaterThan(SEA);
  });

  it("never treats a shoreline as an inner step", () => {
    const map = stepped(100, 5000);
    const built = buildTerrain(map);
    const coastKeys = new Set<number>();
    for (let i = 0; i < built.coast.length; i += 2) coastKeys.add(built.coast[i]);
    for (let i = 0; i < built.steps.length; i += 3) expect(coastKeys.has(built.steps[i])).toBe(false);
  });
});
