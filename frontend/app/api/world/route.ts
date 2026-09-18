import { apiBase } from "../../lib/api";

// Proxies the live world state for the status pill. Unlike the map this is never cached:
// the tick and the policy are exactly the sort of thing a stale answer would misreport.
export const runtime = "nodejs";

// Short on purpose. The pill is decoration; if the API is still waking up the page simply
// goes without it rather than making anyone wait.
const TIMEOUT_MS = 4000;

export async function GET() {
  try {
    const upstream = await fetch(`${apiBase()}/world`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!upstream.ok) {
      return Response.json({ detail: "World state unavailable" }, { status: 503 });
    }
    return new Response(await upstream.text(), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ detail: "World state unavailable" }, { status: 503 });
  }
}
