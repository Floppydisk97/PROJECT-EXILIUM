"use client";

import { useEffect, useState } from "react";
import { ColonyEntry, ColonyManifest, loadColony, loadManifest } from "../lib/colony";
import type { ColonyGround } from "./ground";
import ColonyView from "./ColonyView";

/** Six demo sites rather than one, because the claim being made is that the biome decides the
 *  ground -- and a viewer that can only show one colony cannot show that at all. */
export default function ColonyPicker() {
  const [manifest, setManifest] = useState<ColonyManifest | null>(null);
  const [ground, setGround] = useState<ColonyGround | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadManifest()
      .then((m) => { if (!cancelled) { setManifest(m); setChosen(m.colonies[0]?.name ?? null); } })
      .catch((error) => { if (!cancelled) setFailure(String(error.message ?? error)); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!manifest || !chosen) return;
    const entry = manifest.colonies.find((c) => c.name === chosen);
    if (!entry) return;
    let cancelled = false;
    setGround(null);
    loadColony(entry)
      .then((g) => { if (!cancelled) setGround(g); })
      .catch((error) => { if (!cancelled) setFailure(String(error.message ?? error)); });
    return () => { cancelled = true; };
  }, [manifest, chosen]);

  const entry: ColonyEntry | undefined = manifest?.colonies.find((c) => c.name === chosen);

  return (
    <main className="colony-page">
      <header className="colony-head">
        <h1>Sito di atterraggio</h1>
        <nav className="colony-tabs">
          {manifest?.colonies.map((c) => (
            <button key={c.name} type="button"
                    className={c.name === chosen ? "on" : undefined}
                    onClick={() => setChosen(c.name)}>
              {c.label}
            </button>
          ))}
        </nav>
      </header>

      {failure && <p className="colony-note">{failure}</p>}
      {!failure && !ground && <p className="colony-note">Ricognizione del terreno…</p>}
      {ground && <ColonyView ground={ground} />}

      {ground && entry && (
        <footer className="colony-facts">
          <span><b>{ground.site.biome.replace(/_/g, " ")}</b></span>
          <span>{ground.site.elevation} m</span>
          <span>{ground.site.temperature.toFixed(1)} °C</span>
          <span>{ground.site.rainfall} mm</span>
          {ground.site.river_flow > 0 && <span>fiume {ground.site.river_flow}</span>}
          {ground.site.coastal && <span>costa</span>}
          <span className="colony-spacer" />
          <span><b>{ground.buildable.toLocaleString("it-IT")}</b> esagoni edificabili su {(ground.size ** 2).toLocaleString("it-IT")}</span>
        </footer>
      )}
    </main>
  );
}
