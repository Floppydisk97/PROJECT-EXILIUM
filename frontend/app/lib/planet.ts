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
  if (typeof DecompressionStream === "undefined") {
    // Chrome 80, Firefox 113, Safari 16.4. Older browsers get a sentence rather than a
    // blank sphere and no idea why.
    throw new PlanetUnavailable("Questo browser non sa decomprimere il pianeta.");
  }

  const manifest = await fetchJson<PlanetManifest>("map/manifest.json", signal);
  const response = await fetch(`map/${manifest.file}`, { cache: "force-cache", signal });
  if (!response.ok || !response.body) {
    throw new PlanetUnavailable(`Il pianeta non si è caricato (${response.status}).`);
  }

  const counted: ReadableStream<Uint8Array> = onProgress
    ? response.body.pipeThrough(countingStream(onProgress, manifest.packed_bytes))
    : response.body;
  // The payload is gzip and is deliberately NOT named `.gz`: a static host would set
  // Content-Encoding on that name by guesswork, the browser would unpack it silently, and
  // this line would then fail on bytes already unpacked. One party unpacks, and it is this one.
  //
  // The cast is a lib.dom quirk, not a doubt about the data: DecompressionStream is declared
  // as accepting BufferSource, which does not unify with a ReadableStream<Uint8Array> even
  // though every chunk of one is a BufferSource.
  const gunzip = new DecompressionStream("gzip") as unknown as
    ReadableWritablePair<Uint8Array, Uint8Array>;
  const text = await new Response(counted.pipeThrough(gunzip)).text();
  return JSON.parse(text) as WorldMap;
}

async function fetchJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { cache: "no-cache", signal });
  if (!response.ok) {
    throw new PlanetUnavailable(`Manca il manifesto del pianeta (${response.status}).`);
  }
  return (await response.json()) as T;
}

function countingStream(
  onProgress: (received: number, total: number) => void,
  total: number,
): TransformStream<Uint8Array, Uint8Array> {
  let received = 0;
  return new TransformStream({
    transform(chunk, controller) {
      received += chunk.byteLength;
      onProgress(received, total);
      controller.enqueue(chunk);
    },
  });
}
