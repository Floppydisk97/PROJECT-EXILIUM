// Talking to the authoritative server.
//
// The planet is a file and the colony's ground is a function of it -- neither needs anything
// awake. A CITY does: its stores, its level and what it is busy with are decided by the
// server and cannot be computed here without inventing them. So this is the one part of the
// viewer that depends on a running instance, deliberately and only here.
//
// Which means it must survive a free instance's cold start. `keepKnocking` counts patience by
// the WALL CLOCK, because Render answers a request for a sleeping service with an immediate
// 5xx: counting attempts spends a minute and a half of budget in eighteen seconds, against a
// wake-up that needs fifty.
import { keepKnocking } from "./patience";

export class ApiUnavailable extends Error {}
export class NotAuthorised extends Error {}

/** Where the server is.
 *
 *  Baked at build time, because a static export has no server to ask at runtime. The
 *  localStorage override exists so the same built bundle can be pointed at a backend running
 *  on your own machine without rebuilding it -- which is the difference between trying a
 *  change in ten seconds and in three minutes.
 */
export function apiBase(): string {
  let override: string | null = null;
  try {
    override = localStorage.getItem("exilium.api");
  } catch {
    // Private windows and blocked site data throw rather than returning null.
  }
  const raw = override || process.env.NEXT_PUBLIC_API_URL || "";
  return raw.replace(/\/+$/, "");
}

const TOKEN_KEY = "exilium.token";

export function savedToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function saveToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Nothing to do: the session simply will not be remembered.
  }
}

export type StallForecast = Record<string, number | null>;

export type CityView = {
  id: string;
  name: string;
  level: number;
  stock_milli: Record<string, string>;
  alloy_milli: string;
  settled_at: string;
  policy: string;
  policy_vote: string | null;
  next_upgrade_cost_milli: Record<string, string>;
  next_upgrade_seconds: number;
  supported_level: number;
  stalls_in_seconds: StallForecast;
  busy_until: string | null;
  busy_with: string | null;
};

/** One authenticated call, waiting out a cold start rather than failing into it.
 *
 *  A 401 is NOT retried: a wrong token stays wrong however long you knock, and knocking on it
 *  for ninety seconds tells the player nothing except that the game is broken.
 */
export async function call<T>(
  path: string,
  { method = "GET", body, token, budgetMs = 90_000, signal }: {
    method?: string; body?: unknown; token?: string | null;
    budgetMs?: number; signal?: AbortSignal;
  } = {},
): Promise<T> {
  const base = apiBase();
  if (!base) throw new ApiUnavailable("Nessun server configurato per questa pagina.");
  const bearer = token ?? savedToken();
  if (!bearer) throw new NotAuthorised("Serve un token per parlare con il server.");

  let refusal: Error | null = null;
  const knocked = await keepKnocking<T>({ budgetMs, gapMs: 1500, maxGapMs: 8000 }, async () => {
    const response = await fetch(`${base}${path}`, {
      method,
      signal,
      headers: {
        Authorization: `Bearer ${bearer}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(method === "POST" ? { "Idempotency-Key": crypto.randomUUID() } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).catch(() => null);

    if (response === null) return { done: false };          // rete assente, o istanza morta
    if (response.status === 401 || response.status === 403) {
      refusal = new NotAuthorised("Il server non riconosce questo token.");
      return { done: true, value: null as T };
    }
    // 429 e 5xx sono cio' che dice un'istanza che si sta svegliando o che e' sovraccarica:
    // esattamente i casi in cui insistere e' la risposta giusta.
    if (response.status === 429 || response.status >= 500) return { done: false };
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      refusal = new Error(detail?.detail ?? `Il server ha rifiutato (${response.status}).`);
      return { done: true, value: null as T };
    }
    return { done: true, value: (await response.json()) as T };
  });

  if (refusal) throw refusal;
  if (knocked.value === null) {
    throw new ApiUnavailable(
      `Il server non ha risposto in ${Math.round(knocked.elapsedMs / 1000)} secondi.`,
    );
  }
  return knocked.value;
}

export const myCities = (token?: string) =>
  call<{ id: string; name: string }[]>("/me/cities", { token });
export const readCity = (id: string) => call<CityView>(`/cities/${id}`);
export const upgrade = (id: string) =>
  call<unknown>(`/cities/${id}/upgrade`, { method: "POST" });
export const vote = (id: string, choice: string) =>
  call<unknown>(`/cities/${id}/vote`, { method: "PUT", body: { choice } });
