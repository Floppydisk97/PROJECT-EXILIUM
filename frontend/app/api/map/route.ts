// Proxies the authoritative planet map from the internal API to the browser.
// The map is immutable once generated, so it is safe to cache for a long time.
const API = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  try {
    const upstream = await fetch(`${API}/world/map`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    if (upstream.status === 404) {
      return Response.json({ detail: "World map not generated" }, { status: 404 });
    }
    if (!upstream.ok) {
      return Response.json({ detail: "Map temporarily unavailable" }, { status: 503 });
    }
    const body = await upstream.text();
    return new Response(body, {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
      },
    });
  } catch {
    return Response.json({ detail: "Map temporarily unavailable" }, { status: 503 });
  }
}
