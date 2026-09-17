// Biome ids come from the authoritative backend (worldgen.BIOMES). Colours and labels
// are presentation only; the client never derives geography.
export type Tile = {
  id: number;
  lat: number;
  lon: number;
  center: [number, number, number];
  normal: [number, number, number];
  elevation: number;
  temperature: number;
  rainfall: number;
  biome: string;
  river_flow: number;
  landmass_size: number;
  neighbor_count: number;
  polygon: [number, number, number][];
};

// A river reach, already paired with the tile it drains into by the backend.
export type River = {
  a: [number, number, number];
  b: [number, number, number];
  flow: number;
  ae: number; // elevation at the upstream end, for the drawing radius
  be: number; // elevation at the downstream end (clamped to 0 at the coast)
};

export type WorldMap = {
  name: string;
  seed: string;
  frequency: number;
  sea_level: number;
  tile_count: number;
  land_count: number;
  elevation_max: number;
  relief_gain: number;
  rivers: River[];
  tiles: Tile[];
};

export const BIOMES: Record<string, { label: string; color: number }> = {
  ocean: { label: "Oceano", color: 0x2a5a86 },
  lake: { label: "Lago", color: 0x3d84bd },
  sea_ice: { label: "Banchisa", color: 0xd3e3ef },
  ice_sheet: { label: "Calotta glaciale", color: 0xf3f8fc },
  snow_cap: { label: "Vetta innevata", color: 0xe9eef3 },
  bare_rock: { label: "Roccia d'alta quota", color: 0xa3a19b },
  tundra: { label: "Tundra", color: 0xa3a48c },
  boreal_forest: { label: "Foresta boreale", color: 0x548a62 },
  temperate_forest: { label: "Foresta temperata", color: 0x6d9a4e },
  temperate_swamp: { label: "Palude temperata", color: 0x59886d },
  arid_shrubland: { label: "Steppa arida", color: 0xb6a86c },
  desert: { label: "Deserto", color: 0xe2cb8e },
  tropical_rainforest: { label: "Foresta pluviale", color: 0x549f45 },
  tropical_swamp: { label: "Palude tropicale", color: 0x568f6f },
};

// Water never hosts a colony, even where a lake sits above sea level.
export const WATER_BIOMES = new Set(["ocean", "lake", "sea_ice"]);

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
