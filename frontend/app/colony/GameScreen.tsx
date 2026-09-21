"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { loadPlanet } from "../lib/planet";
import type { WorldMap } from "../globe/biomes";
import { tileAt } from "../globe/terrain";
import {
  CityView, NotAuthorised, apiBase, call, myCities, readCity, saveToken, savedToken,
} from "../lib/api";
import CityPanel from "../city/CityPanel";
import { Generated, Site, generate, seedFor } from "./citygen";
import ColonyView, { Camera } from "./ColonyView";
import MiniMap from "./MiniMap";
import { Menu, ResourceBar, ScoutBar } from "./Hud";

/** Lo schermo di gioco.
 *
 *  Due modi, e la differenza non e' cosmetica: una casella che NON e' tua si puo' solo
 *  guardare -- il pianeta e' un file, nessun server serve -- mentre la tua colonia ha uno
 *  stato che solo il server conosce. Quindi il terreno e' sempre disegnato qui, e la barra
 *  sopra dice cose diverse a seconda che ci sia qualcosa da governare.
 *
 *      /colonia            la tua colonia, con le risorse e i comandi
 *      /colonia?tile=N     una casella qualunque, in ricognizione
 */
type Ground = { made: Generated; name: string; scouting: boolean };

export default function GameScreen({ tileId }: { tileId: number | null }) {
  const [stage, setStage] = useState("Lettura del pianeta…");
  const [ground, setGround] = useState<Ground | null>(null);
  const [city, setCity] = useState<CityView | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [camera, setCamera] = useState<Camera | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const goTo = useRef<((x: number, y: number) => void) | null>(null);

  const onCamera = useCallback((next: Camera) => setCamera(next), []);

  // Il terreno: una volta sola, perche' 590.000 celle sono mezzo secondo di lavoro vero.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (tileId === null) {
          // La tua colonia. Il server dice il SEME e il sito; le celle le fa questo browser.
          if (!apiBase() || !savedToken()) {
            setFailure("Serve un token per vedere la tua colonia. Apri il menu e accedi.");
            return;
          }
          setStage("Chiedo al server dove sei sceso…");
          const mine = await myCities();
          if (!mine.length) { setFailure("Questo token non ha colonie."); return; }
          const seat = await call<{ seed: string; size: number; site: Site }>(
            `/cities/${mine[0].id}/ground`,
          );
          if (cancelled) return;
          setStage("Crescita del terreno…");
          await new Promise((resolve) => requestAnimationFrame(resolve));
          const made = generate(seat.seed, seat.site, seat.size);
          if (cancelled) return;
          setGround({ made, name: mine[0].name, scouting: false });
          setCity(await readCity(mine[0].id));
          return;
        }

        const map: WorldMap = await loadPlanet((received, total) => {
          if (!cancelled) {
            setStage(`Lettura del pianeta… ${Math.round((received / Math.max(1, total)) * 100)}%`);
          }
        });
        if (cancelled) return;
        // Il file del pianeta porta solo la terra -- l'oceano e' nove decimi della sfera e non
        // ci atterra nessuno -- quindi un id assente non e' una casella mancante.
        const index = map.tiles.id.indexOf(tileId);
        if (index < 0) {
          setFailure("Su quella casella c'è oceano: nessuna colonia può scendere lì.");
          return;
        }
        const chosen = tileAt(map, index);
        if (chosen.elevation < 0 || ["ocean", "lake", "sea_ice"].includes(chosen.biome)) {
          setFailure("Su quella casella c'è acqua: nessuna colonia può scendere lì.");
          return;
        }
        setStage("Ricognizione del terreno…");
        const site: Site = {
          biome: chosen.biome, elevation: chosen.elevation, temperature: chosen.temperature,
          rainfall: chosen.rainfall, coastal: chosen.coastal,
          // La portata memorizzata e' deflusso accumulato, e ogni casella di terra ne ha:
          // passata cosi' com'e', metteva un fiume in mezzo a OGNI colonia del pianeta. La
          // soglia e' la stessa su cui il globo disegna i suoi fiumi e viaggia col pianeta,
          // quindi il terreno e il globo dicono la stessa cosa della stessa casella.
          river_flow: chosen.river_flow >= map.river_min_flow ? chosen.river_flow : 0,
        };
        const seed = await seedFor(map.seed, chosen.id);
        // Un fotogramma prima, cosi' il messaggio e' a schermo quando il filo principale se ne
        // va per mezzo secondo: un blocco silenzioso somiglia a un crollo.
        await new Promise((resolve) => requestAnimationFrame(resolve));
        const made = generate(seed, site);
        if (!cancelled) setGround({ made, name: `Casella ${chosen.id}`, scouting: true });
      } catch (error) {
        if (!cancelled) {
          setFailure(String((error as Error).message ?? error));
          if (error instanceof NotAuthorised) saveToken(null);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [tileId]);

  // Il mondo cammina da solo: le risorse si riallineano invece di mostrare un passato.
  const refresh = useCallback(async () => {
    if (!city) return;
    try { setCity(await readCity(city.id)); } catch { /* il prossimo giro riprova */ }
  }, [city]);

  useEffect(() => {
    if (!city) return;
    const timer = setInterval(refresh, 30_000);
    return () => clearInterval(timer);
  }, [city, refresh]);

  const planet = () => { window.location.href = "/"; };

  if (failure) {
    return (
      <main className="game">
        <div className="hud-top">
          <button className="hud-icon" onClick={planet} title="Torna al pianeta">🌍</button>
          <div className="hud-resources"><span className="hud-scout-title">Colonia</span></div>
        </div>
        <p className="colony-note">{failure}</p>
      </main>
    );
  }

  if (!ground) {
    return (
      <main className="game">
        <div className="hud-top">
          <button className="hud-icon" onClick={planet} title="Torna al pianeta">🌍</button>
          <div className="hud-resources"><span className="hud-scout-title">{stage}</span></div>
        </div>
      </main>
    );
  }

  const site = ground.made.site;
  const economy = ground.made.economy;

  return (
    <main className="game">
      {city ? (
        <ResourceBar city={city} onMenu={() => setMenuOpen(true)} onPlanet={planet} />
      ) : (
        <ScoutBar
          title={ground.name}
          onPlanet={planet}
          facts={[
            { label: "bioma", value: site.biome.replace(/_/g, " ") },
            { label: "cibo", value: String(economy.food) },
            { label: "legname", value: String(economy.timber) },
            { label: "pietra", value: String(economy.stone) },
            { label: "minerale", value: String(economy.ore) },
            { label: "vento/sole/acqua/calore",
              value: `${economy.wind}/${economy.sun}/${economy.water}/${economy.heat}` },
            { label: "edificabili", value: economy.room.toLocaleString("it-IT") },
          ]}
        />
      )}

      <div className="game-stage">
        <ColonyView ground={ground.made} onCamera={onCamera} goTo={goTo} />
      </div>

      <div className="hud-corner">
        <MiniMap ground={ground.made} camera={camera} goTo={goTo} />
        <div className="hud-buttons">
          <button onClick={planet} title="Il pianeta">🌍 Pianeta</button>
          {city && (
            <button onClick={() => setPanelOpen((open) => !open)} title="Governo della colonia">
              🏛 {panelOpen ? "Chiudi" : "Governo"}
            </button>
          )}
          <button onClick={() => setMenuOpen(true)} title="Menu">☰ Menu</button>
        </div>
      </div>

      {city && panelOpen && (
        <aside className="game-panel">
          <CityPanel city={city} onChanged={refresh} />
        </aside>
      )}

      {menuOpen && (
        <Menu
          onClose={() => setMenuOpen(false)}
          onPlanet={planet}
          onCity={() => { setPanelOpen(true); setMenuOpen(false); }}
          onForget={() => { saveToken(null); window.location.href = "/citta"; }}
        />
      )}
    </main>
  );
}
