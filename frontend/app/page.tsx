"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

type CitySummary = { id: string; name: string; is_capital: boolean };
type Player = { id: string; handle: string; entered_exilium_prime: boolean; cities: CitySummary[] };
type Cell = { id: number; q: number; r: number; terrain: string };
type City = {
  id: string; name: string; alloy_milli: string; production_milli_per_second: string;
  extractors: number; policy: string; settled_at: string; cell: Cell | null;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Richiesta fallita" }));
    throw new Error(body.detail ?? "Richiesta fallita");
  }
  return response.status === 204 ? (undefined as T) : response.json() as Promise<T>;
}

function units(milli: string) {
  return (Number(milli) / 1000).toFixed(3);
}

export default function Home() {
  const [player, setPlayer] = useState<Player | null>(null);
  const [city, setCity] = useState<City | null>(null);
  const [cells, setCells] = useState<Cell[]>([]);
  const [mode, setMode] = useState<"register" | "login">("register");
  const [message, setMessage] = useState("Caricamento…");
  const [busy, setBusy] = useState(false);
  const foundationAttempt = useRef<{ payload: string; key: string } | null>(null);
  const extractorAttempt = useRef<string | null>(null);

  const hydrate = useCallback(async () => {
    try {
      const me = await api<Player>("/me");
      setPlayer(me);
      if (me.cities.length) {
        setCity(await api<City>(`/cities/${me.cities[0].id}`));
        setCells([]);
      } else if (me.entered_exilium_prime) {
        setCells(await api<Cell[]>("/worlds/exilium-prime/cells"));
        setCity(null);
      }
      setMessage("");
    } catch {
      setPlayer(null); setCity(null); setMessage("");
    }
  }, []);

  useEffect(() => { void hydrate(); }, [hydrate]);

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await api(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify({ handle: data.get("handle"), password: data.get("password") }),
      });
      await hydrate();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Accesso fallito");
    } finally { setBusy(false); }
  }

  async function enter() {
    setBusy(true);
    try {
      await api("/worlds/exilium-prime/enter", { method: "POST", body: "{}" });
      await hydrate();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ingresso fallito");
    } finally { setBusy(false); }
  }

  async function found(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const payload = JSON.stringify({ name: data.get("name"), cell_id: Number(data.get("cell_id")) });
    if (foundationAttempt.current?.payload !== payload) {
      foundationAttempt.current = { payload, key: crypto.randomUUID() };
    }
    setBusy(true);
    try {
      await api("/worlds/exilium-prime/colonies", {
        method: "POST",
        headers: { "Idempotency-Key": foundationAttempt.current.key }, body: payload,
      });
      foundationAttempt.current = null;
      await hydrate();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Fondazione fallita");
    } finally { setBusy(false); }
  }

  async function buildExtractor() {
    if (!city) return;
    extractorAttempt.current ??= crypto.randomUUID();
    setBusy(true);
    try {
      await api(`/cities/${city.id}/buildings/extractor`, {
        method: "POST", headers: { "Idempotency-Key": extractorAttempt.current }, body: "{}",
      });
      extractorAttempt.current = null;
      await hydrate();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Costruzione fallita");
    } finally { setBusy(false); }
  }

  async function logout() {
    await api("/auth/logout", { method: "POST", body: "{}" });
    setPlayer(null); setCity(null); setCells([]); setMessage("");
  }

  return (
    <main>
      <h1>Project Exilium</h1>
      <p>Primo insediamento nel mondo persistente exilium-prime.</p>
      {message && <p role="status">{message}</p>}
      {!player && (
        <section>
          <h2>{mode === "register" ? "Registrazione" : "Accesso"}</h2>
          <form onSubmit={submitAuth}>
            <label>Handle <input name="handle" required minLength={3} maxLength={32} pattern="[A-Za-z0-9_]+" autoComplete="username" /></label>
            <label>Password <input name="password" type="password" required minLength={10} maxLength={128} autoComplete={mode === "register" ? "new-password" : "current-password"} /></label>
            <button disabled={busy}>{mode === "register" ? "Crea account" : "Entra"}</button>
          </form>
          <button type="button" onClick={() => setMode(mode === "register" ? "login" : "register")}>
            {mode === "register" ? "Ho già un account" : "Crea un account"}
          </button>
        </section>
      )}
      {player && (
        <>
          <p>Comandante: <strong>{player.handle}</strong> <button onClick={logout}>Esci</button></p>
          {!player.entered_exilium_prime && (
            <section><h2>exilium-prime</h2><button disabled={busy} onClick={enter}>Entra nel mondo</button></section>
          )}
          {player.entered_exilium_prime && !city && (
            <section>
              <h2>Fonda la prima colonia</h2>
              <form onSubmit={found}>
                <label>Nome <input name="name" required maxLength={80} /></label>
                <label>Cella <select name="cell_id" required defaultValue="">
                  <option value="" disabled>Scegli una cella</option>
                  {cells.map(cell => <option key={cell.id} value={cell.id}>({cell.q}, {cell.r}) · {cell.terrain}</option>)}
                </select></label>
                <button disabled={busy || !cells.length}>Fonda colonia</button>
              </form>
            </section>
          )}
          {city && (
            <section>
              <h2>{city.name}</h2>
              <dl>
                <dt>Cella</dt><dd>{city.cell ? `(${city.cell.q}, ${city.cell.r}) · ${city.cell.terrain}` : "Legacy"}</dd>
                <dt>Lega disponibile</dt><dd>{units(city.alloy_milli)}</dd>
                <dt>Produzione</dt><dd>{units(city.production_milli_per_second)} lega/s</dd>
                <dt>Estrattori</dt><dd>{city.extractors}</dd>
                <dt>Politica</dt><dd>{city.policy}</dd>
                <dt>Produzione liquidata alle</dt><dd>{new Date(city.settled_at).toLocaleString()}</dd>
              </dl>
              <button disabled={busy || Number(city.alloy_milli) < 60000} onClick={buildExtractor}>Costruisci estrattore · 60 lega</button>
              <button disabled={busy} onClick={() => void hydrate()}>Aggiorna produzione</button>
            </section>
          )}
        </>
      )}
    </main>
  );
}
