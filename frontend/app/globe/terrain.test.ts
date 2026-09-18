// The geometry builders are the part of the client that can be wrong without anything
// complaining: the type checker sees arrays of numbers, and a screenshot only shows the
// frame someone happened to look at. These tests check the arithmetic directly.
import { describe, expect, it } from "vitest";
import {
  buildCliffs, buildGlyphs, buildRivers, buildTerrain, GROUND, HILL_ELEVATION, ICE,
  MOUNTAIN_ELEVATION, SEA, SHELF, tileAt, tileRadius, tileRelief, tileSpacing,
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
    // The real backend tiles a subdivided icosahedron, so the count follows from the
    // frequency: 10f^2 + 2. Widths are sized against the spacing that count implies, and a
    // handful of hand-built tiles must not be mistaken for a planet with four of them.
    tile_count: 10 * 20 ** 2 + 2, land_count: tiles.filter((t) => t.elevation >= 0).length,
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

  // The ground used to be hillshaded against a fixed light, which is meaningless once the
  // terrain is flat: the same biome would read as two different greens depending only on
  // where it sat, and no reader can match that against a legend. Two identical tiles facing
  // opposite ways must now come out identically.
  it("colours a biome by what it is, not by which way it faces", () => {
    const facing: [number, number, number] = [0.52, -0.55, 0.65];
    const away: [number, number, number] = [-0.52, 0.55, -0.65];
    const map = world([
      { ring: [0, 1, 2], elevation: 400, biome: "tundra", center: facing, normal: facing },
      { ring: [1, 0, 3], elevation: 400, biome: "tundra", center: away, normal: away },
    ], CORNERS);
    const { colors } = buildTerrain(map);
    // Same biome, same id-independent jitter aside: the two differ only by tileJitter, so
    // compare the ratio between channels, which the jitter scales uniformly.
    const one = [colors[0], colors[1], colors[2]];
    const other = [colors[3 * 9], colors[3 * 9 + 1], colors[3 * 9 + 2]];
    expect(one[0] / one[1]).toBeCloseTo(other[0] / other[1], 6);
    expect(one[2] / one[1]).toBeCloseTo(other[2] / other[1], 6);
  });
});

describe("tile geometry", () => {
  it("puts each tile on the layer it belongs to", () => {
    const map = world([
      { ring: [0, 1, 2], elevation: 7000, biome: "snow_cap" },
      { ring: [1, 0, 3], elevation: -50, biome: "sea_ice" },
      { ring: [2, 3, 0], elevation: -400, biome: "ocean" },
    ], CORNERS);
    expect(tileRadius(map, 0)).toBe(GROUND);   // the highest ground there is, still flat
    expect(tileRadius(map, 1)).toBe(ICE);
    expect(tileRadius(map, 2)).toBe(SHELF);
    // Water layers stack in the order the cliffs assume: the shell is under everything.
    expect(SEA).toBeLessThan(SHELF);
    expect(SHELF).toBeLessThan(ICE);
    expect(ICE).toBeLessThan(1);
  });

  it("puts all dry land on one shell, whatever its elevation", () => {
    const map = world([
      { ring: [0, 1, 2], elevation: 0, biome: "desert" },
      { ring: [1, 0, 3], elevation: 6800, biome: "snow_cap" },
    ], CORNERS);
    expect(tileRadius(map, 0)).toBe(tileRadius(map, 1));
  });

  it("reads elevation as a relief class instead of as a height", () => {
    expect(tileRelief(0)).toBe("flat");
    expect(tileRelief(HILL_ELEVATION - 1)).toBe("flat");
    expect(tileRelief(HILL_ELEVATION)).toBe("hill");
    expect(tileRelief(MOUNTAIN_ELEVATION - 1)).toBe("hill");
    expect(tileRelief(MOUNTAIN_ELEVATION)).toBe("mountain");
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
      expect(Math.max(...radii)).toBeCloseTo(GROUND, 6);
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
    const fine = { ...world([], CORNERS, reach(100)), frequency: 80, tile_count: 10 * 80 ** 2 + 2 };
    // Four times the frequency is sixteen times the tiles, so a quarter of the spacing --
    // and a quarter of the river, to within the two pentagon-poles the formula adds.
    expect(widthOf(fine)).toBeCloseTo(widthOf(coarse) / 4, 5);
  });

  it("skips a reach that goes nowhere instead of emitting a degenerate ribbon", () => {
    const stuck = world([], CORNERS, {
      a: [1, 0, 0], b: [1, 0, 0], flow: [50], ae: [100], be: [100],
    });
    expect(buildRivers(stuck, RIVER_MINOR, RIVER_MAJOR).reaches).toBe(0);
  });
});

describe("tileSpacing", () => {
  it("is the distance that makes the tiles cover the sphere exactly", () => {
    const map = twoLand();
    const d = tileSpacing(map);
    // Each hexagonal cell covers (sqrt(3)/2) d^2, and together they cover 4*pi.
    expect((Math.sqrt(3) / 2) * d * d * map.tile_count).toBeCloseTo(4 * Math.PI, 9);
    // The formula this replaced -- 2*pi / (1.5 * frequency) -- was 3.48 times too large.
    expect((2 * Math.PI) / (1.5 * map.frequency) / d).toBeCloseTo(3.48, 2);
  });
});

describe("buildGlyphs", () => {
  const ground = (elevation: number, biome = "temperate_forest") =>
    world([{ ring: [0, 1, 2], elevation, biome, center: [0, 1, 0] }], CORNERS);

  it("marks a hill with one peak and a mountain with two, and flat ground with none", () => {
    expect(buildGlyphs(ground(300)).triangles).toBe(0);
    expect(buildGlyphs(ground(HILL_ELEVATION)).triangles).toBe(1);
    expect(buildGlyphs(ground(MOUNTAIN_ELEVATION)).triangles).toBe(2);
  });

  it("never marks water, however high it sits", () => {
    // A lake can rest well above sea level, and an alpine tarn is still not a mountain.
    expect(buildGlyphs(ground(MOUNTAIN_ELEVATION, "lake")).triangles).toBe(0);
    expect(buildGlyphs(ground(MOUNTAIN_ELEVATION, "ice_sheet")).triangles).toBe(2);
  });

  it("sizes buffers exactly, with no slack to draw past", () => {
    const glyphs = buildGlyphs(ground(MOUNTAIN_ELEVATION));
    expect(glyphs.positions).toHaveLength(glyphs.triangles * 9);
    expect(glyphs.colors).toHaveLength(glyphs.triangles * 9);
  });

  it("keeps the glyph inside its own tile and just off the ground", () => {
    const map = ground(MOUNTAIN_ELEVATION);
    const glyphs = buildGlyphs(map);
    const span = tileSpacing(map);
    for (let v = 0; v < glyphs.positions.length; v += 3) {
      const x = glyphs.positions[v], y = glyphs.positions[v + 1], z = glyphs.positions[v + 2];
      expect(Math.hypot(x, y, z)).toBeGreaterThan(GROUND);
      expect(Math.hypot(x, y, z)).toBeLessThan(GROUND * 1.01);
      // Angular distance from the tile centre, which sits at [0, 1, 0].
      expect(Math.acos(Math.min(1, y / Math.hypot(x, y, z)))).toBeLessThan(span * 0.5);
    }
  });

  it("stands the glyph up towards north, wherever the tile sits", () => {
    // Two tiles on the same meridian: each glyph's apex must be further north than its
    // base, or a range drawn near the limb would appear to have toppled over.
    for (const centre of [[0, 1, 0], [0, 0.6, 0.8]] as [number, number, number][]) {
      const map = world([{ ring: [0, 1, 2], elevation: HILL_ELEVATION, biome: "tundra", center: centre }], CORNERS);
      const p = buildGlyphs(map).positions;
      const latitude = (i: number) => Math.asin(p[i * 3 + 2] / Math.hypot(p[i * 3], p[i * 3 + 1], p[i * 3 + 2]));
      expect(latitude(2)).toBeGreaterThan(latitude(0));   // apex above the left base corner
      expect(latitude(2)).toBeGreaterThan(latitude(1));   // and above the right one
    }
  });
});
