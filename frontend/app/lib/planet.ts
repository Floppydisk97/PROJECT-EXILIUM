// Loading the planet from a file instead of from a server.
//
// The map is immutable: generated once, changed only by a migration. It never needed to be
// an API call, and making it one is what put a sleeping free instance on the critical path
// of simply looking at the world -- a day of 502s, 429s and cold starts to deliver four
// megabytes that never change. As a static asset it cannot be unreachable, cannot be slow to
// wake, and costs nothing to serve. It is also the shape the game wants: a downloadable
// client ships its world as data.
//
// Two files. `manifest.json` is a few hundred bytes and is always fetched fresh; it names the
// payload, whose name carries a hash of its content. So the payload can be cached forever and
// a new world simply has a new name -- the staleness question disappears instead of being
// managed.
import type { WorldMap } from "../globe/biomes";

export type PlanetManifest = {
  file: string;
  name: string;
  seed: string;
  frequency: number;
  generator_version: number;
  tile_count: number;
  land_count: number;
  raw_bytes: number;
  packed_bytes: number;
};

export class PlanetUnavailable extends Error {}

/** Fetch, unpack and parse the planet. `onProgress` reports packed bytes received out of the
 *  total the manifest promises -- real progress, not a spinner: four megabytes over a phone
 *  connection is long enough that a visitor deserves to know it is moving. */
export async function loadPlanet(
  onProgress?: (received: number, total: number) => void,
  signal?: AbortSignal,
): Promise<WorldMap> {
  const manifest = await fetchJson<PlanetManifest>("/map/manifest.json", signal);
  const response = await fetch(`/map/${manifest.file}`, { cache: "force-cache", signal });
  if (!response.ok || !response.body) {
    throw new PlanetUnavailable(`Il pianeta non si è caricato (${response.status}).`);
  }

  const packed = await readAll(response.body, onProgress, manifest.packed_bytes);

  // The payload is gzip, and is deliberately NOT named `.gz`: a static host that trusted that
  // extension would set Content-Encoding, the browser would unpack it silently, and unpacking
  // it again here would fail on bytes already unpacked. But "deliberately" is a decision made
  // on this side of the wire, and the CDN is on the other -- so instead of trusting the
  // arrangement, we look: 1f 8b is gzip's magic number, and its absence means somebody already
  // did the work. Either way the page draws.
  const text = looksGzipped(packed)
    ? await gunzip(packed)
    : new TextDecoder().decode(packed);

  try {
    return JSON.parse(text) as WorldMap;
  } catch {
    throw new PlanetUnavailable("Il pianeta è arrivato danneggiato.");
  }
}

async function gunzip(packed: Uint8Array): Promise<string> {
  if (typeof DecompressionStream === "undefined") {
    // Chrome 80, Firefox 113, Safari 16.4. Older browsers get a sentence rather than a blank
    // sphere and no idea why. Asked here rather than on the way in, because a payload the CDN
    // already unpacked does not need this at all.
    throw new PlanetUnavailable("Questo browser non sa decomprimere il pianeta.");
  }
  return await new Response(
        new Blob([packed as BlobPart]).stream().pipeThrough(
          new DecompressionStream("gzip") as unknown as
        ReadableWritablePair<Uint8Array, Uint8Array>,
    ),
  ).text();
}

const GZIP_MAGIC = [0x1f, 0x8b];

function looksGzipped(bytes: Uint8Array): boolean {
  return bytes.length > 2 && bytes[0] === GZIP_MAGIC[0] && bytes[1] === GZIP_MAGIC[1];
}

/** Drain the body, reporting progress as it goes. Reading it ourselves rather than piping
 *  straight into the decompressor is what lets us look at the first bytes before deciding
 *  whether to decompress at all. */
async function readAll(
  body: ReadableStream<Uint8Array>,
  onProgress: ((received: number, total: number) => void) | undefined,
  total: number,
): Promise<Uint8Array> {
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.byteLength;
    onProgress?.(received, total);
  }
  const all = new Uint8Array(received);
  let at = 0;
  for (const chunk of chunks) { all.set(chunk, at); at += chunk.byteLength; }
  return all;
}

async function fetchJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { cache: "no-cache", signal });
  if (!response.ok) {
    throw new PlanetUnavailable(`Manca il manifesto del pianeta (${response.status}).`);
  }
  return (await response.json()) as T;
}
