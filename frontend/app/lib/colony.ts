// Loading a colony's ground. Same arrangement as the planet: a small manifest that is always
// read fresh, and payloads whose names carry a hash of their content so they can be cached for
// ever. And the same refusal to trust the CDN about whether it unpacked anything.
//
// The paths are rooted, not relative. A relative `colony/manifest.json` resolves against the
// page that asked for it, so from `/colonia/` it became `/colonia/colony/manifest.json` and
// 404ed. The planet's loader has the same shape and only works because that page sits at the
// root -- which is luck, not design, so it is rooted now too.
import type { ColonyGround } from "../colony/ground";

export type ColonyEntry = {
  name: string; label: string; file: string; biome: string;
  size: number; packed_bytes: number; raw_bytes: number;
};
export type ColonyManifest = { world_seed: string; colonies: ColonyEntry[] };

export class ColonyUnavailable extends Error {}

export async function loadManifest(signal?: AbortSignal): Promise<ColonyManifest> {
  const response = await fetch("/colony/manifest.json", { cache: "no-cache", signal });
  if (!response.ok) throw new ColonyUnavailable(`Manca l'elenco delle colonie (${response.status}).`);
  return (await response.json()) as ColonyManifest;
}

export async function loadColony(entry: ColonyEntry, signal?: AbortSignal): Promise<ColonyGround> {
  const response = await fetch(`/colony/${entry.file}`, { cache: "force-cache", signal });
  if (!response.ok) throw new ColonyUnavailable(`Terreno non caricato (${response.status}).`);
  const packed = new Uint8Array(await response.arrayBuffer());
  // 1f 8b is gzip's magic number. Its absence means the CDN already unpacked this, and
  // unpacking it again would fail on bytes that are already plain -- see lib/planet.ts.
  const text = packed.length > 2 && packed[0] === 0x1f && packed[1] === 0x8b
    ? await new Response(
        new Blob([packed as BlobPart]).stream().pipeThrough(
          new DecompressionStream("gzip") as unknown as ReadableWritablePair<Uint8Array, Uint8Array>,
        ),
      ).text()
    : new TextDecoder().decode(packed);
  return JSON.parse(text) as ColonyGround;
}
