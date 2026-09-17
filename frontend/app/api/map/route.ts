import { gzipSync } from "node:zlib";
import { apiBase } from "../../lib/api";

// Proxies the authoritative planet map from the internal API to the browser.
// The map is immutable once generated, so a successful response is cached in this
// process and served pre-gzipped: the raw payload is several MB, gzip cuts it to ~1 MB.
export const runtime = "nodejs";

// On a free instance the API sleeps when idle and takes the better part of a minute to
// come back; while it boots, Render's router answers 502/503. One timeout is therefore not
// an outage, so this keeps knocking for about a minute and a half before giving up.
const ATTEMPT_TIMEOUT_MS = 25_000;
const ATTEMPTS = 4;

type Upstream =
  | { kind: "ok"; raw: string }
  | { kind: "missing" }     // the world has genuinely never been generated
  | { kind: "unavailable" }; // still not answering after all the patience we have

let cache: { gz: ArrayBuffer; raw: string } | null = null;
let inFlight: Promise<Upstream> | null = null;

async function fetchUpstream(): Promise<Upstream> {
  let backoff = 1500;
  for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
    try {
      const upstream = await fetch(`${apiBase()}/world/map`, {
        cache: "no-store",
        signal: AbortSignal.timeout(ATTEMPT_TIMEOUT_MS),
      });
      if (upstream.status === 404) return { kind: "missing" };
      if (upstream.ok) return { kind: "ok", raw: await upstream.text() };
    } catch {
      // Timed out, or the connection was refused: either way the instance is still coming up.
    }
    if (attempt < ATTEMPTS - 1) {
      await new Promise((resolve) => setTimeout(resolve, backoff));
      backoff *= 2;
    }
  }
  return { kind: "unavailable" };
}

export async function GET(request: Request) {
  if (!cache) {
    // Everyone who arrives during a cold start waits on the same wake-up, not their own.
    inFlight ??= fetchUpstream().finally(() => { inFlight = null; });
    const result = await inFlight;
    if (result.kind === "missing") {
      return Response.json({ detail: "World map not generated" }, { status: 404 });
    }
    if (result.kind === "unavailable") {
      return Response.json(
        { detail: "Map temporarily unavailable", waking: true },
        { status: 503, headers: { "Retry-After": "20" } },
      );
    }
    const buf = gzipSync(result.raw);
    // A standalone ArrayBuffer is an unambiguous BodyInit across TS lib versions.
    const gz = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
    cache = { raw: result.raw, gz };
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
