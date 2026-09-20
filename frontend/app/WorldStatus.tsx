"use client";

import { useEffect, useState } from "react";
import type { PlanetManifest } from "./lib/planet";

/** What world you are looking at.
 *
 *  This used to show the live tick and policy, fetched from the API. On a static site that
 *  would be the one thread still tied to a sleeping free instance -- and, being cross-origin,
 *  it would need CORS on the authoritative server for a pill that would almost never manage
 *  to render. Half a dependency is worse than none: it brings back the whole class of failure
 *  this change exists to remove, in exchange for decoration.
 *
 *  So the pill now names the world from the manifest, which ships with the page and is always
 *  true. The live tick belongs in the game client, which will talk to the API properly --
 *  authenticated, cross-origin by design, and about cities rather than about scenery.
 */
export default function WorldStatus() {
  const [planet, setPlanet] = useState<PlanetManifest | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/map/manifest.json", { cache: "no-cache" });
        if (!response.ok) return;
        const manifest = (await response.json()) as PlanetManifest;
        if (!cancelled) setPlanet(manifest);
      } catch {
        // No pill, no problem: the globe is the page.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (!planet) return null;
  return (
    <div className="status-pill">
      <b>{planet.name}</b> · seme <b>{planet.seed}</b> ·{" "}
      {planet.tile_count.toLocaleString("it-IT")} caselle
    </div>
  );
}
