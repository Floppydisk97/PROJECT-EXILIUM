"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiUnavailable, CityView, NotAuthorised, apiBase, myCities, readCity, saveToken, savedToken,
} from "../lib/api";
import { stallNote, units } from "./format";
import CityPanel from "./CityPanel";
import ServerField from "./ServerField";

const RESOURCES = ["food", "timber", "stone", "ore", "alloy"] as const;
const LABEL: Record<string, string> = {
  food: "Cibo", timber: "Legname", stone: "Pietra", ore: "Minerale", alloy: "Lega",
  energy: "Corrente",
};

/** La colonia, come la vede il suo proprietario.
 *
 *  E' la prima pagina del visore che NON puo' essere statica: magazzini, livello e cio' che la
 *  citta' sta facendo sono decisi dal server e non si possono calcolare qui senza inventarli.
 *  Quindi e' anche l'unica che deve sopravvivere al risveglio di un'istanza addormentata --
 *  se ne occupa `lib/api`, e qui si vede solo come un'attesa dichiarata invece che un errore.
 */
export default function CityScreen() {
  const [token, setToken] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [cityId, setCityId] = useState<string | null>(null);
  const [city, setCity] = useState<CityView | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);
  // La pagina e' pre-renderizzata a build time, dove non esistono ne' localStorage ne'
  // l'indirizzo del server. Decidere cosa mostrare PRIMA di essere nel browser significa
  // disegnare una cosa e poi un'altra, che React chiama disallineamento di idratazione e
  // che qui si vedeva come un errore in console a ogni caricamento.
  const [inBrowser, setInBrowser] = useState(false);

  useEffect(() => {
    setInBrowser(true);
    setToken(savedToken());
  }, []);

  const refresh = useCallback(async (id: string) => {
    try {
      setCity(await readCity(id));
      setFailure(null);
    } catch (error) {
      setFailure(String((error as Error).message));
      if (error instanceof NotAuthorised) { saveToken(null); setToken(null); }
    }
  }, []);

  // Entrare: il token dice quali colonie sono tue, e per ora ne hai una.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      setWorking("Sveglio il server…");
      try {
        const mine = await myCities(token);
        if (cancelled) return;
        if (!mine.length) { setFailure("Questo token non ha colonie."); return; }
        setCityId(mine[0].id);
        await refresh(mine[0].id);
      } catch (error) {
        if (!cancelled) {
          setFailure(String((error as Error).message));
          if (error instanceof NotAuthorised) { saveToken(null); setToken(null); }
        }
      } finally {
        if (!cancelled) setWorking(null);
      }
    })();
    return () => { cancelled = true; };
  }, [token, refresh]);

  // Il mondo cammina da solo: la pagina si riallinea invece di mostrare un passato.
  useEffect(() => {
    if (!cityId || !city) return;
    const timer = setInterval(() => refresh(cityId), 30_000);
    return () => clearInterval(timer);
  }, [cityId, city, refresh]);

  if (!inBrowser) return <main className="city-page" />;

  if (!apiBase()) {
    return (
      <main className="city-page">
        <header className="city-head"><a className="colony-back" href="/">← Pianeta</a>
          <h1>La tua colonia</h1></header>
        <p className="city-note">
          Questa pagina parla con il server autoritativo, e nessun server è configurato per
          questa copia del visore. Il globo e il terreno funzionano lo stesso: sono file.
        </p>
        <ServerField />
      </main>
    );
  }

  if (!token) {
    return (
      <main className="city-page">
        <header className="city-head"><a className="colony-back" href="/">← Pianeta</a>
          <h1>La tua colonia</h1></header>
        <form
          className="city-login"
          onSubmit={(event) => { event.preventDefault(); saveToken(typed.trim()); setToken(typed.trim()); }}
        >
          <label htmlFor="token">Token della colonia</label>
          <input id="token" value={typed} onChange={(e) => setTyped(e.target.value)}
                 placeholder="incolla qui il token" autoComplete="off" spellCheck={false} />
          <button type="submit" disabled={!typed.trim()}>Entra</button>
          <p className="city-note">
            Il token te lo dà il comando che crea la colonia. Resta su questo browser e non
            va da nessun'altra parte.
          </p>
          <ServerField />
          {failure && <p className="city-alarm">{failure}</p>}
        </form>
      </main>
    );
  }

  return (
    <main className="city-page">
      <header className="city-head">
        <a className="colony-back" href="/">← Pianeta</a>
        <h1>{city?.name ?? "Colonia"}</h1>
        {city && <span className="city-level">livello {city.level} / {city.supported_level}</span>}
        <span className="colony-spacer" />
        <button className="city-quiet" onClick={() => { saveToken(null); setToken(null); setCity(null); }}>
          Esci
        </button>
      </header>

      {working && <p className="city-note">{working}</p>}
      {failure && <p className="city-alarm">{failure}</p>}

      {city && (
        <>
          <section className="city-stores">
            {RESOURCES.map((resource) => {
              const held = Number(city.stock_milli[resource] ?? 0);
              const stalls = city.stalls_in_seconds?.[resource];
              return (
                <div key={resource} className="city-store">
                  <div className="city-store-head">
                    <b>{LABEL[resource]}</b>
                    <span className={stalls === 0 || stalls === null ? "city-stalled" : ""}>
                      {stallNote(stalls)}
                    </span>
                  </div>
                  <div className="city-amount">{units(held)}</div>
                </div>
              );
            })}
          </section>

          <CityPanel city={city} onChanged={() => refresh(city.id)} />
        </>
      )}
    </main>
  );
}
