import Globe from "./globe/Globe";
import { apiBase } from "./lib/api";

export const dynamic = "force-dynamic";

type World = {
  policy: "balanced" | "industrial";
  last_tick: string;
  next_tick_at: string;
  server_time: string;
};

async function loadWorld(): Promise<World | null> {
  try {
    const response = await fetch(`${apiBase()}/world`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    return await response.json() as World;
  } catch {
    return null;
  }
}

export default async function Home() {
  const world = await loadWorld();
  return (
    <main>
      <Globe />
      {world && (
        <div className="status-pill">
          Tick <b>{world.last_tick}</b> · Politica <b>{world.policy}</b>
        </div>
      )}
    </main>
  );
}
