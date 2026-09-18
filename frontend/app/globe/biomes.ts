// Biome ids come from the authoritative backend (worldgen.BIOMES). Colours and labels
// are presentation only; the client never derives geography.
//
// The map arrives in columns rather than as a list of tile objects: at production size a
// JSON object per tile would spend more bytes repeating field names than on the geography.
// Polygon corners are face centroids shared by three tiles each, so they live in one pool
// and a tile only quotes indices into it.
export type TileColumns = {
  id: number[];
  center: number[];        // flat, 3 per tile
  // The server's terrain normals, computed against the relief it used to be drawn with.
  // Nothing reads them since the ground became one shell; they are still sent, and dropping
  // them from the payload would save about a quarter of it.
  normal: number[];        // flat, 3 per tile
  elevation: number[];
  temperature: number[];
  rainfall: number[];
  biome: number[];         // index into WorldMap.biome_names
  river_flow: number[];
  landmass_size: number[];
  neighbor_count: number[];
  ring: number[];          // corner indices, flat
  ring_offset: number[];   // one more entry than there are tiles
};

export type RiverColumns = {
  a: number[];   // flat, 3 per reach: the upstream end
  b: number[];   // flat, 3 per reach: the tile it drains into
  flow: number[];
  ae: number[];  // elevation at each end, for the drawing radius
  be: number[];
};

export type WorldMap = {
  name: string;
  seed: string;
  frequency: number;
  sea_level: number;
  tile_count: number;
  land_count: number;
  elevation_max: number;
  // Shared with the server when the client extruded each tile to its own height. The ground
  // is flat now, so nothing here uses it; elevation_max still bounds the relief classes.
  relief_gain: number;
  river_min_flow: number;   // the smallest reach the backend sends, for the width ramp
  biome_names: string[];
  corners: number[];       // flat, 3 per corner
  tiles: TileColumns;
  rivers: RiverColumns;
};

// One tile, materialised only when the panel needs to show it.
export type Tile = {
  index: number;
  id: number;
  lat: number;
  lon: number;
  elevation: number;
  temperature: number;
  rainfall: number;
  biome: string;
  river_flow: number;
  landmass_size: number;
  neighbor_count: number;
};

export const BIOMES: Record<string, { label: string; color: number }> = {
  ocean: { label: "Oceano", color: 0x2a5a86 },
  lake: { label: "Lago", color: 0x3d84bd },
  sea_ice: { label: "Banchisa", color: 0xd3e3ef },
  ice_sheet: { label: "Calotta glaciale", color: 0xe9f0f6 },
  snow_cap: { label: "Vetta innevata", color: 0xe0e8f0 },
  bare_rock: { label: "Roccia d'alta quota", color: 0x9a9287 },
  tundra: { label: "Tundra", color: 0x9ea089 },
  boreal_forest: { label: "Foresta boreale", color: 0x548a62 },
  temperate_forest: { label: "Foresta temperata", color: 0x6d9a4e },
  temperate_swamp: { label: "Palude temperata", color: 0x59886d },
  arid_shrubland: { label: "Steppa arida", color: 0xb3a263 },
  desert: { label: "Deserto", color: 0xdcc084 },
  tropical_rainforest: { label: "Foresta pluviale", color: 0x549f45 },
  tropical_swamp: { label: "Palude tropicale", color: 0x568f6f },
};

// Water never hosts a colony, even where a lake sits above sea level.
export const WATER_BIOMES = new Set(["ocean", "lake", "sea_ice"]);

// The shelf ring is shaded by its real depth, from the surf line out to where the sea floor
// drops away; past that the client draws open ocean as one smooth shell.
export const SHELF_SHALLOW = 0x6ba3c4;
// The deep end of the shelf is exactly the open-ocean colour, so the ring fades into the
// sea instead of ending on a seam.
export const OCEAN_DEEP = 0x35688f;
export const SHELF_DEEP = OCEAN_DEEP;
export const SHELF_MAX_DEPTH = 900;

export const RIVER_MINOR = 0x4e9ed0;
export const RIVER_MAJOR = 0x8ad6f5;

// How much procedural grain a surface takes up close: canopy and broken rock are noisy,
// snow and water are nearly smooth. Keeps a biome from reading as one flat plastic colour.
const GRAIN: Record<string, number> = {
  tropical_rainforest: 0.38,
  temperate_forest: 0.36,
  boreal_forest: 0.36,
  tropical_swamp: 0.24,
  temperate_swamp: 0.24,
  bare_rock: 0.36,
  arid_shrubland: 0.22,
  tundra: 0.22,
  desert: 0.15,
  snow_cap: 0.18,
  ice_sheet: 0.16,
  sea_ice: 0.08,
  lake: 0.05,
  ocean: 0.05,
};

export function biomeGrain(id: string): number {
  return GRAIN[id] ?? 0.2;
}

export function biomeLabel(id: string): string {
  return BIOMES[id]?.label ?? id;
}

export function biomeColor(id: string): number {
  return BIOMES[id]?.color ?? 0x888888;
}

// Landmasses read very differently at a glance; name them by size so the panel can say
// whether a site sits on a continent or on a rock in the middle of the ocean.
export function landmassLabel(size: number): string {
  if (size <= 0) return "—";
  if (size <= 3) return `Isolotto (${size} tile)`;
  if (size <= 30) return `Isola (${size} tile)`;
  if (size <= 400) return `Arcipelago maggiore (${size} tile)`;
  if (size <= 4000) return `Subcontinente (${size} tile)`;
  return `Continente (${size} tile)`;
}
