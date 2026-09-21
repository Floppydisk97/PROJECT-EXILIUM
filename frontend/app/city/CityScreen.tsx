"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiUnavailable, CityView, NotAuthorised, apiBase, buildWork, demolish, myCities, readCity,
  saveToken, savedToken, setRunning, upgrade, vote,
} from "../lib/api";
import { howLong, missingFor, stallNote, units } from "./format";

const RESOURCES = ["food", "timber", "stone", "ore", "alloy"] as const;
const LABEL: Record<string, string> = {
  food: "Cibo", timber: "Legname", stone: "Pietra", ore: "Minerale", alloy: "Lega",
  energy: "Corrente",
};

// Il server parla la lingua del dominio, che è inglese come tutto il codice. Al giocatore no.
const BUSY: Record<string, string> = { upgrade: "avanzamento" };

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

  async function act(what: string, run: () => Promise<unknown>) {
    if (!cityId) return;
    setWorking(what);
    try {
      await run();
      await refresh(cityId);
    } catch (error) {
      setFailure(String((error as Error).message));
    } finally {
      setWorking(null);
    }
  }

  if (!inBrowser) return <main className="city-page" />;

  if (!apiBase()) {
    return (
      <main className="city-page">
        <p className="city-note">
          Questa pagina parla con il server autoritativo, e nessun server è configurato per
          questa copia del visore. Il globo e il terreno funzionano lo stesso: sono file.
        </p>
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
          {failure && <p className="city-alarm">{failure}</p>}
        </form>
      </main>
    );
  }

  const cost = city?.next_upgrade_cost_milli ?? {};
  const short = city ? missingFor(cost, city.stock_milli) : null;
  const busy = Boolean(city?.busy_until);
  const atFoodCeiling = city ? city.level >= city.supported_level : false;

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

          <section className="city-actions">
            <div className="city-card">
              <h2>Costruire</h2>
              <p className="city-cost">
                {Object.entries(cost).map(([resource, amount]) =>
                  `${LABEL[resource]} ${units(amount)}`).join(" · ")}
                {" — "}{howLong(city.next_upgrade_seconds)}
              </p>
              {busy ? (
                <p className="city-note">
                  In corso: {BUSY[city.busy_with ?? ""] ?? city.busy_with}, fino alle{" "}
                  {new Date(city.busy_until!).toLocaleString("it-IT")}. Una cosa alla volta.
                </p>
              ) : atFoodCeiling ? (
                <p className="city-alarm">
                  La terra non sfama un altro livello. Il cibo di questo sito regge fino al
                  livello {city.supported_level}: crescere oltre non è permesso, invece di
                  essere permesso e poi pagato con una colonia che non si salva più.
                </p>
              ) : short ? (
                <p className="city-note">
                  Manca {Object.entries(short).map(([r, gap]) =>
                    `${LABEL[r].toLowerCase()} ${units(gap)}`).join(" e ")}.
                </p>
              ) : null}
              <button
                disabled={busy || Boolean(short) || atFoodCeiling || working !== null}
                onClick={() => act("Impegno la colonia…", () => upgrade(city.id))}
              >
                Avanza al livello {city.level + 1}
              </button>
            </div>

            <div className="city-card city-wide">
              <h2>Impianti</h2>
              {/* La corrente e' un bilancio, non un magazzino: prodotta contro pretesa. Se la
                  seconda supera la prima, TUTTI gli impianti rallentano insieme -- non se ne
                  sceglie uno da spegnere, perche' quella scelta e' del giocatore. */}
              <p className={city.power_used > city.power_made ? "city-alarm" : "city-note"}>
                Corrente: <b>{city.power_made}</b> prodotta · <b>{city.power_used}</b> pretesa
                {city.power_used > city.power_made
                  ? ` — non basta, tutto gira al ${Math.round(city.work_permille / 10)}%.`
                  : city.work_permille < 1000
                    ? ` — un ingresso è finito: si gira al ${Math.round(city.work_permille / 10)}%.`
                    : " — tutto a pieno regime."}
              </p>

              <table className="city-works">
                <tbody>
                  {Object.entries(city.catalogue).map(([kind, work]) => {
                    const built = city.works[kind] ?? 0;
                    const asleep = city.works_idle[kind] ?? 0;
                    const live = built - asleep;
                    return (
                      <tr key={kind}>
                        <td>
                          <b>{work.label}</b>
                          <span className="city-dim">
                            {work.from
                              ? ` — ${work.power} corrente/s qui (attitudine ${city.site_power[work.from]})`
                              : ` — ${Object.entries(work.inputs).map(([r, n]) => `${LABEL[r].toLowerCase()} ${n}`).join(" + ")}`
                                + ` + ${work.draw} corrente → `
                                + Object.entries(work.outputs).map(([r, n]) => `${LABEL[r].toLowerCase()} ${n}`).join(" + ")}
                          </span>
                        </td>
                        <td className="city-count">
                          {built ? `${live} acc.${asleep ? ` / ${asleep} in pausa` : ""}` : "—"}
                        </td>
                        <td className="city-buttons">
                          <button
                            disabled={working !== null || live <= 0}
                            title="Spegnine uno: non consuma, non produce, non chiede corrente"
                            onClick={() => act("Spengo…", () => setRunning(city.id, kind, live - 1))}
                          >
                            Pausa
                          </button>
                          <button
                            disabled={working !== null || asleep <= 0}
                            onClick={() => act("Riaccendo…", () => setRunning(city.id, kind, live + 1))}
                          >
                            Accendi
                          </button>
                          <button
                            disabled={working !== null || built <= 0}
                            title="Senza rimborso: ciò che è stato messo in opera è stato messo in opera"
                            onClick={() => {
                              if (confirm(`Abbattere un impianto «${work.label}»? Non c'è rimborso.`)) {
                                act("Abbatto…", () => demolish(city.id, kind));
                              }
                            }}
                          >
                            Abbatti
                          </button>
                          <button
                            disabled={busy || working !== null}
                            onClick={() => act(`Costruisco ${work.label.toLowerCase()}…`,
                                               () => buildWork(city.id, kind))}
                          >
                            Costruisci ({Object.entries(work.cost_milli)
                              .map(([r, a]) => `${LABEL[r].toLowerCase()} ${units(a)}`).join(", ")}
                            {` — ${howLong(work.seconds)}`})
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="city-note">
                {busy
                  ? city.busy_with === "work"
                    ? `In costruzione, pronto alle ${new Date(city.busy_until!).toLocaleTimeString("it-IT")}.`
                    : "La colonia sta già facendo altro: una cosa alla volta."
                  : "Costruire occupa la colonia; accendere e spegnere no — è un interruttore."}
              </p>
            </div>

            <div className="city-card">
              <h2>Politica del mondo</h2>
              <p className="city-note">
                In vigore: <b>{city.policy === "industrial" ? "industriale" : "bilanciata"}</b>.
                Il tuo voto vale uno e resta finché non lo cambi.
              </p>
              <div className="city-vote">
                {["balanced", "industrial"].map((choice) => (
                  <button
                    key={choice}
                    className={city.policy_vote === choice ? "on" : ""}
                    disabled={working !== null}
                    onClick={() => act("Voto…", () => vote(city.id, choice))}
                  >
                    {choice === "industrial" ? "Industriale" : "Bilanciata"}
                  </button>
                ))}
              </div>
              <p className="city-note">
                L&apos;industriale raccoglie di più e nutre di meno. Non può affamarti:
                il tetto della colonia è calcolato sulla politica peggiore.
              </p>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
