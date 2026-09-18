"use client";

import { useEffect, useState } from "react";

type World = {
  policy: "balanced" | "industrial";
  last_tick: string;
  next_tick_at: string;
  server_time: string;
};

/** The tick and policy pill. Deliberately a client component: fetching this during the
 *  server render held the whole page for as long as the API took to answer, which on a
 *  free instance waking from sleep is most of a minute -- the shell, the globe's own
 *  loading notice and all. Decoration must never gate the page it decorates. */
export default function WorldStatus() {
  const [world, setWorld] = useState<World | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/world");
        if (!response.ok) return;
        const state = (await response.json()) as World;
        if (!cancelled) setWorld(state);
      } catch {
        // No pill, no problem: the globe is the page.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (!world) return null;
  return (
    <div className="status-pill">
      Tick <b>{world.last_tick}</b> · Politica <b>{world.policy}</b>
    </div>
  );
}
