// Biome ids come from the authoritative backend (worldgen.BIOMES). Colours and labels
// are presentation only; the client never derives geography.
export type Tile = {
  id: number;
  lat: number;
  lon: number;
  center: [number, number, number];
  elevation: number;
  temperature: number;
  rainfall: number;
  biome: string;
  neighbor_count: number;
  polygon: [number, number, number][];
};

export type WorldMap = {
  name: string;
  seed: string;
  frequency: number;
  sea_level: number;
  tile_count: number;
  land_count: number;
  tiles: Tile[];
};

export const BIOMES: Record<string, { label: string; color: number }> = {
  ocean: { label: "Ocean", color: 0x2a5a86 },
  sea_ice: { label: "Sea ice", color: 0xc5d8e4 },
  ice_sheet: { label: "Ice sheet", color: 0xf2f7fb },
  tundra: { label: "Tundra", color: 0x9a9a83 },
  boreal_forest: { label: "Boreal forest", color: 0x4d7d5c },
  temperate_forest: { label: "Temperate forest", color: 0x6f9950 },
  temperate_swamp: { label: "Temperate swamp", color: 0x5b8a70 },
  arid_shrubland: { label: "Arid shrubland", color: 0xb3a56a },
  desert: { label: "Desert", color: 0xdcc58a },
  tropical_rainforest: { label: "Tropical rainforest", color: 0x4f8f45 },
  tropical_swamp: { label: "Tropical swamp", color: 0x4e8567 },
};

export function biomeLabel(id: string): string {
  return BIOMES[id]?.label ?? id;
}

export function biomeColor(id: string): number {
  return BIOMES[id]?.color ?? 0x888888;
}
