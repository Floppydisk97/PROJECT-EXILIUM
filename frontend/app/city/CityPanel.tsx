"use client";

import { useState } from "react";
import {
  CityView, buildWork, demolish, setRunning, upgrade, vote,
} from "../lib/api";
import { howLong, missingFor, units } from "./format";

// Il server parla la lingua del dominio, che è inglese come tutto il codice. Al giocatore no.
const BUSY: Record<string, string> = { upgrade: "avanzamento", work: "impianto" };
const LABEL: Record<string, string> = {
  food: "Cibo", timber: "Legname", stone: "Pietra", ore: "Minerale", alloy: "Lega",
  energy: "Corrente",
};

/** I comandi della colonia: costruire, governare gli impianti, votare.
 *
 *  Tenuti separati dalla schermata che li ospita, perche' hanno DUE case: la pagina della
 *  citta' e il pannello dentro il gioco. Duplicarli avrebbe significato che un cambio alle
 *  regole si vede in un posto e non nell'altro, che e' il genere di divergenza che questo
 *  progetto ha gia' pagato quattro volte.
 */
export default function CityPanel(
  { city, onChanged }: { city: CityView; onChanged: () => Promise<void> | void },
) {
  const [working, setWorking] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  async function act(what: string, run: () => Promise<unknown>) {
    setWorking(what);
    setFailure(null);
    try {
      await run();
      await onChanged();
    } catch (error) {
      setFailure(String((error as Error).message));
    } finally {
      setWorking(null);
    }
  }

  const cost = city.next_upgrade_cost_milli ?? {};
  const short = missingFor(cost, city.stock_milli);
  const busy = Boolean(city.busy_until);
  const atFoodCeiling = city.level >= city.supported_level;

  return (
    <>
      {working && <p className="city-note">{working}</p>}
      {failure && <p className="city-alarm">{failure}</p>}
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
                      {/* Il prezzo sta qui e non sul bottone: dentro il pannello stretto del
                          gioco un bottone lungo una riga di testo andava a capo tre volte. */}
                      <span className="city-price">
                        {Object.entries(work.cost_milli)
                          .map(([r, a]) => `${LABEL[r].toLowerCase()} ${units(a)}`).join(", ")}
                        {` — ${howLong(work.seconds)}`}
                      </span>
                    </td>
                    <td className="city-count">
                      {built ? `${live} acc.${asleep ? ` / ${asleep} in pausa` : ""}` : ""}
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
                        Costruisci
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
  );
}
