import { gzipSync } from "node:zlib";
import { apiBase } from "../../lib/api";

// Proxies the authoritative planet map from the internal API to the browser.
// The map is immutable once generated, so a successful response is cached in this
// process and served pre-gzipped: the raw payload is several MB, gzip cuts it to ~1 MB.
export const runtime = "nodejs";

let cache: { gz: ArrayBuffer; raw: string } | null = null;

export async function GET(request: Request) {
  if (!cache) {
    try {
      const upstream = await fetch(`${apiBase()}/world/map`, {
        cache: "no-store",
        signal: AbortSignal.timeout(30000), // tolerate a free-tier API cold start
      });
      if (upstream.status === 404) {
        return Response.json({ detail: "World map not generated" }, { status: 404 });
      }
      if (!upstream.ok) {
        return Response.json({ detail: "Map temporarily unavailable" }, { status: 503 });
      }
      const raw = await upstream.text();
      const buf = gzipSync(raw);
      // A standalone ArrayBuffer is an unambiguous BodyInit across TS lib versions.
      const gz = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
      cache = { raw, gz };
    } catch {
      return Response.json({ detail: "Map temporarily unavailable" }, { status: 503 });
    }
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
    Vary: "Accept-Encoding",
  };
  if ((request.headers.get("accept-encoding") ?? "").includes("gzip")) {
    return new Response(cache.gz, { status: 200, headers: { ...headers, "Content-Encoding": "gzip" } });
  }
  return new Response(cache.raw, { status: 200, headers });
}
