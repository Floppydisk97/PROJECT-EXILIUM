import { gzipSync } from "node:zlib";
import { apiBase } from "../../lib/api";
import { keepKnocking, type Knock } from "../../lib/patience";

// Proxies the authoritative planet map from the internal API to the browser.
// The map is immutable once generated, so a successful response is cached in this
// process and served pre-gzipped: the raw payload is several MB, gzip cuts it to ~1 MB.
export const runtime = "nodejs";

// On a free instance the API sleeps when idle and takes the better part of a minute to come
// back; while it boots, Render's router answers 502/503 *immediately*. So the wait is counted
// in wall-clock time, not in attempts -- see lib/patience.ts for the morning that cost.
//
// The budget stays under Render's own 100 s request ceiling: a proxy that waits longer than
// the platform will only get cut off mid-wait and report the outage it was trying to avoid.
const WAKE_BUDGET_MS = 90_000;
const FIRST_GAP_MS = 1_500;
const MAX_GAP_MS = 8_000;
const ATTEMPT_TIMEOUT_MS = 20_000;

type Upstream =
  | { kind: "ok"; raw: string }
  | { kind: "missing" }     // the world has genuinely never been generated
  | { kind: "unavailable" }; // still not answering after all the patience we have

let cache: { gz: ArrayBuffer; raw: string } | null = null;
let inFlight: Promise<Upstream> | null = null;

async function fetchUpstream(): Promise<Upstream> {
  const knocked = await keepKnocking<Upstream>(
    { budgetMs: WAKE_BUDGET_MS, gapMs: FIRST_GAP_MS, maxGapMs: MAX_GAP_MS },
    async (attempt): Promise<Knock<Upstream>> => {
      try {
        const upstream = await fetch(`${apiBase()}/world/map`, {
          cache: "no-store",
          signal: AbortSignal.timeout(ATTEMPT_TIMEOUT_MS),
        });
        if (upstream.status === 404) return { done: true, value: { kind: "missing" } };
        if (upstream.ok) return { done: true, value: { kind: "ok", raw: await upstream.text() } };
        // A waking instance is a 502/503 from Render's router, and this branch used to be
        // silent because only the `catch` below logged. That silence is why an unreachable
        // API and a merely slow one left identical traces, and telling them apart took a
        // morning of reading logs that did not contain the answer.
        console.warn(`[map] attempt ${attempt}: upstream answered ${upstream.status}`);
      } catch (reason) {
        console.warn(`[map] attempt ${attempt} failed:`, reason);
      }
      return { done: false };
    },
  );
  if (knocked.value) return knocked.value;
  console.error(
    `[map] giving up on ${apiBase()} after ${knocked.attempts} attempts ` +
    `over ${Math.round(knocked.elapsedMs / 1000)}s`,
  );
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
