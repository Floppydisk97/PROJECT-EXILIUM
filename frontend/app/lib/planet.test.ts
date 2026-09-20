// The loading path had no test, and it is where the bugs actually shipped: asset paths that
// resolved against the page instead of the root, and a payload that might arrive already
// unpacked. Both were found by eye. These hold the decisions that survived.
import { describe, expect, it, vi, afterEach } from "vitest";
import { PlanetUnavailable, loadPlanet } from "./planet";
import { gzipSync } from "node:zlib";

const PLANET = {
  name: "T", seed: "s", frequency: 2, sea_level: 0, tile_count: 42, land_count: 2,
  river_min_flow: 20, biome_names: ["ocean"], corners: [],
  tiles: { id: [], center: [], elevation: [], temperature: [], rainfall: [], biome: [],
           river_flow: [], landmass_size: [], neighbor_count: [], coastal: [],
           ring: [], ring_offset: [0] },
  rivers: { a: [], b: [], flow: [], ae: [], be: [] },
};

function serve(payload: Uint8Array, manifest: Record<string, unknown> = {}) {
  const asked: string[] = [];
  const fetchMock = vi.fn(async (path: string) => {
    asked.push(path);
    if (path.endsWith("manifest.json")) {
      return new Response(JSON.stringify({
        file: "planet-abc.bin", name: "T", seed: "s", frequency: 2, generator_version: 8,
        tile_count: 42, land_count: 2, raw_bytes: 10, packed_bytes: payload.byteLength,
        ...manifest,
      }), { status: 200 });
    }
    return new Response(payload as BlobPart, { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return asked;
}

afterEach(() => vi.unstubAllGlobals());

describe("loading the planet", () => {
  it("asks for its files from the ROOT, whatever page is asking", async () => {
    // The bug this pins: a relative `map/manifest.json` asked from /colonia/ became
    // /colonia/map/manifest.json. The planet viewer only worked because it sits at the root,
    // which was luck and not design.
    const asked = serve(gzipSync(JSON.stringify(PLANET)));
    await loadPlanet();
    for (const path of asked) expect(path.startsWith("/")).toBe(true);
    expect(asked).toEqual(["/map/manifest.json", "/map/planet-abc.bin"]);
  });

  it("unpacks a gzipped payload", async () => {
    serve(gzipSync(JSON.stringify(PLANET)));
    expect((await loadPlanet()).seed).toBe("s");
  });

  it("accepts a payload a CDN already unpacked", async () => {
    // The arrangement -- do not name it .gz, so nobody sets Content-Encoding -- is a decision
    // made on our side of the wire. The CDN is on the other side. So the bytes are looked at
    // rather than trusted: no 1f 8b means somebody already did the work.
    serve(new TextEncoder().encode(JSON.stringify(PLANET)));
    expect((await loadPlanet()).seed).toBe("s");
  });

  it("reports progress against the size the manifest promised", async () => {
    const packed = gzipSync(JSON.stringify(PLANET));
    serve(packed);
    const seen: [number, number][] = [];
    await loadPlanet((received, total) => seen.push([received, total]));
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.at(-1)).toEqual([packed.byteLength, packed.byteLength]);
  });

  it("says what went wrong instead of drawing a blank sphere", async () => {
    serve(new TextEncoder().encode("{ non e' json"));
    await expect(loadPlanet()).rejects.toBeInstanceOf(PlanetUnavailable);

    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 404 })));
    await expect(loadPlanet()).rejects.toThrow(/manifesto/i);
  });
});
