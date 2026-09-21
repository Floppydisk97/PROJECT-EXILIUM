"use client";

import { useEffect, useState } from "react";
import { loadPlanet } from "../lib/planet";
import type { WorldMap } from "../globe/biomes";
import { tileAt } from "../globe/terrain";
import { Generated, Site, generate, seedFor } from "./citygen";
import ColonyView from "./ColonyView";

/** The ground of one tile, generated here rather than asked of a server.
 *
 *  The planet is a file and the colony is a function of it, so the whole chain -- pick a tile,
 *  see what you would be landing on -- runs with nothing awake anywhere. The SERVER remains
 *  the authority for anything that gets decided; this is for looking, and `citygen.test.ts`
 *  holds this copy to the server's cell for cell.
 */
export default function ColonyPicker({ tileId }: { tileId: number | null }) {
  const [stage, setStage] = useState("Lettura del pianeta…");
  const [ground, setGround] = useState<Generated | null>(null);
  const [tile, setTile] = useState<ReturnType<typeof tileAt> | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const map: WorldMap = await loadPlanet((received, total) => {
          if (!cancelled) {
            setStage(`Lettura del pianeta… ${Math.round((received / Math.max(1, total)) * 100)}%`);
          }
        });
        if (cancelled) return;
        // The planet file carries land only -- the ocean is nine tenths of the sphere and
        // nobody lands on it -- so an id that is not in it is not a missing tile, it is water.
        const index = tileId === null ? -1 : map.tiles.id.indexOf(tileId);
        if (index < 0) {
          setFailure(
            tileId === null
              ? "Nessuna casella scelta: torna al pianeta e scegline una."
              : "Su quella casella c'è oceano: nessuna colonia può scendere lì.",
          );
          return;
        }
        const chosen = tileAt(map, index);
        if (chosen.elevation < 0 || ["ocean", "lake", "sea_ice"].includes(chosen.biome)) {
          setFailure("Su quella casella c'è acqua: nessuna colonia può scendere lì.");
          return;
        }
        setTile(chosen);

        setStage("Ricognizione del terreno…");
        const site: Site = {
          biome: chosen.biome, elevation: chosen.elevation, temperature: chosen.temperature,
          rainfall: chosen.rainfall, river_flow: chosen.river_flow, coastal: chosen.coastal,
        };
        const seed = await seedFor(map.seed, chosen.id);
        // A frame first, so the message is on screen before the main thread goes away for a
        // couple of seconds: 590k cells is real work and a silent freeze looks like a crash.
        await new Promise((resolve) => requestAnimationFrame(resolve));
        const made = generate(seed, site);
        if (!cancelled) setGround(made);
      } catch (error) {
        if (!cancelled) setFailure(String((error as Error).message ?? error));
      }
    })();
    return () => { cancelled = true; };
  }, [tileId]);

  return (
    <main className="colony-page">
      <header className="colony-head">
        <a className="colony-back" href="/">← Pianeta</a>
        <h1>{tile ? `Casella ${tile.id}` : "Sito di atterraggio"}</h1>
        {tile && (
          <span className="colony-coords">
            {tile.lat.toFixed(2)}°, {tile.lon.toFixed(2)}°
          </span>
        )}
      </header>

      {failure && <p className="colony-note">{failure}</p>}
      {!failure && !ground && <p className="colony-progress">{stage}</p>}
      {ground && <ColonyView ground={ground} />}

      {ground && (
        <footer className="colony-facts">
          <span><b>{ground.site.biome.replace(/_/g, " ")}</b></span>
          <span>{ground.site.elevation} m</span>
          <span>{ground.site.temperature.toFixed(1)} °C</span>
          <span>{ground.site.rainfall} mm</span>
          {ground.site.river_flow > 0 && <span>fiume {ground.site.river_flow}</span>}
          {ground.site.coastal && <span>costa</span>}
          <span className="colony-spacer" />
          {/* Cio' che il sito VALE, non solo com'e' fatto. Sono gli stessi tre numeri che il
              server scrive sulla riga della colonia quando si atterra -- mostrarli prima e'
              l'unica cosa che rende la scelta del sito una scelta invece di una formalita'. */}
          <span title="Fertilità della terra su cui si può costruire">
            cibo <b>{ground.economy.food}</b>
          </span>
          <span title="Vegetazione in piedi: legname, una volta sgomberata">
            legname <b>{ground.economy.timber}</b>
          </span>
          <span title="Quota di roccia e ghiaia sulla mappa">
            pietra <b>{ground.economy.stone}</b>
          </span>
          <span title="Filoni: l'unica ricchezza che non sta in superficie — la decide la quota">
            minerale <b>{ground.economy.ore}</b>
          </span>
          {/* L'energia non si raccoglie: e' l'attitudine del LUOGO a produrne. Mostrata qui
              perche' un sito povero di tutto puo' essere il migliore del pianeta per il sole,
              e chi sceglie dove scendere deve poterlo sapere prima. */}
          <span title="Vento, sole, acqua, calore: quanta corrente sa dare questo posto">
            energia <b>{ground.economy.wind}</b>/<b>{ground.economy.sun}</b>/
            <b>{ground.economy.water}</b>/<b>{ground.economy.heat}</b>
          </span>
          <span title="Verde e palude da sgomberare: allunga ogni avanzamento">
            fatica <b>{ground.economy.effort}</b>
          </span>
          <span title="Celle edificabili: quanto cresce la colonia prima di stringersi">
            spazio <b>{ground.economy.room.toLocaleString("it-IT")}</b> su{" "}
            {(ground.size ** 2).toLocaleString("it-IT")}
          </span>
          <span>{((ground.size * ground.cell_metres) / 1000).toFixed(1)} km di lato</span>
        </footer>
      )}
    </main>
  );
}
