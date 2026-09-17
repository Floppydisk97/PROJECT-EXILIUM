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
  neighbors: number[];
  polygon: [number, number, number][];
};

export type WorldMap = {
  name: string;
  seed: string;
  frequency: number;
  sea_level: number;
  tile_count: number;
  tiles: Tile[];
};

export const BIOMES: Record<string, { label: string; color: number }> = {
  ocean: { label: "Ocean", color: 0x1b3a5c },
  sea_ice: { label: "Sea ice", color: 0x9fb8c8 },
  ice_sheet: { label: "Ice sheet", color: 0xe8f1f6 },
  tundra: { label: "Tundra", color: 0x7c7e6d },
  boreal_forest: { label: "Boreal forest", color: 0x2f5d43 },
  temperate_forest: { label: "Temperate forest", color: 0x4a7a3a },
  temperate_swamp: { label: "Temperate swamp", color: 0x3f6b57 },
  arid_shrubland: { label: "Arid shrubland", color: 0x9a8f5c },
  desert: { label: "Desert", color: 0xc9b079 },
  tropical_rainforest: { label: "Tropical rainforest", color: 0x2f6b2f },
  tropical_swamp: { label: "Tropical swamp", color: 0x37614a },
};

export function biomeLabel(id: string): string {
  return BIOMES[id]?.label ?? id;
}

export function biomeColor(id: string): number {
  return BIOMES[id]?.color ?? 0x888888;
}
