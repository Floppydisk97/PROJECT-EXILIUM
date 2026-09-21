"use client";

import type { CityView } from "../lib/api";
import { stallShort, units } from "../city/format";

/** Le risorse, in alto, come in un gioco di civilta'.
 *
 *  Un valore e un VERSO: quanto ne hai e cosa sta succedendo. Il secondo numero e' quello che
 *  conta davvero -- un magazzino pieno che scende e uno vuoto che sale hanno lo stesso aspetto
 *  se si mostra solo il primo.
 */
const RESOURCES: { key: string; label: string; glyph: string }[] = [
  { key: "food", label: "Cibo", glyph: "🌾" },
  { key: "timber", label: "Legname", glyph: "🪵" },
  { key: "stone", label: "Pietra", glyph: "🪨" },
  { key: "ore", label: "Minerale", glyph: "⛏" },
  { key: "alloy", label: "Lega", glyph: "🔩" },
];

export function ResourceBar(
  { city, onMenu, onPlanet }:
  { city: CityView; onMenu: () => void; onPlanet: () => void },
) {
  const short = city.power_used > city.power_made;
  return (
    <div className="hud-top">
      <button className="hud-icon" onClick={onPlanet} title="Torna al pianeta">🌍</button>

      <div className="hud-resources">
        {RESOURCES.map(({ key, label, glyph }) => {
          const stalls = city.stalls_in_seconds?.[key];
          return (
            <span key={key} className="hud-pill" title={label}>
              <b className="hud-glyph">{glyph}</b>
              <span className="hud-value">{units(city.stock_milli[key] ?? 0)}</span>
              <span className={stalls === 0 ? "hud-full" : "hud-rate"}>
                {stallShort(stalls)}
              </span>
            </span>
          );
        })}
        <span className={`hud-pill ${short ? "hud-warn" : ""}`} title="Corrente: prodotta / pretesa">
          <b className="hud-glyph">⚡</b>
          <span className="hud-value">{city.power_made}/{city.power_used}</span>
          {short && <span className="hud-rate">{Math.round(city.work_permille / 10)}%</span>}
        </span>
      </div>

      <div className="hud-right">
        <span className="hud-clock" title="Ora del mondo">
          {new Date(city.settled_at).toLocaleString("it-IT", {
            day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
          })}
        </span>
        <span className="hud-level">liv. {city.level}/{city.supported_level}</span>
        <button className="hud-icon" onClick={onMenu} title="Menu">☰</button>
      </div>
    </div>
  );
}

/** Cio' che il terreno sa dare, quando si sta guardando una casella che non e' nostra. */
export function ScoutBar(
  { title, facts, onPlanet }:
  { title: string; facts: { label: string; value: string }[]; onPlanet: () => void },
) {
  return (
    <div className="hud-top">
      <button className="hud-icon" onClick={onPlanet} title="Torna al pianeta">🌍</button>
      <div className="hud-resources">
        <span className="hud-scout-title">{title}</span>
        {facts.map(({ label, value }) => (
          <span key={label} className="hud-pill" title={label}>
            <span className="hud-rate">{label}</span>
            <span className="hud-value">{value}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function Menu(
  { onClose, onPlanet, onCity, onForget, server }:
  { onClose: () => void; onPlanet: () => void; onCity: () => void;
    onForget: () => void; server: string },
) {
  return (
    <div className="hud-menu-back" onClick={onClose}>
      <div className="hud-menu" onClick={(event) => event.stopPropagation()}>
        <h2>Menu</h2>
        <button onClick={onPlanet}>🌍 Il pianeta</button>
        <button onClick={onCity}>🏛 Governo della colonia</button>
        <hr />
        <h3>Impostazioni</h3>
        <p className="hud-menu-note">
          Server: <code>{server || "nessuno"}</code>
        </p>
        <p className="hud-menu-note">
          Il terreno lo disegna questo browser, dal seme che il server conserva: muoversi e
          ingrandire non chiedono niente a nessuno.
        </p>
        <button onClick={onForget}>Esci e dimentica il token</button>
        <button className="hud-menu-close" onClick={onClose}>Chiudi</button>
      </div>
    </div>
  );
}
