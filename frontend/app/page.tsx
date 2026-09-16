export const dynamic = "force-dynamic";

type World = {
  policy: "balanced" | "industrial";
  last_tick: string;
  next_tick_at: string;
  server_time: string;
};

async function loadWorld(): Promise<World | null> {
  try {
    const response = await fetch(`${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/world`, {
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
      <h1>Project Exilium</h1>
      <p>Fondazione tecnica del mondo persistente. Tick globale alle 00:00 UTC.</p>
      {world ? (
        <dl>
          <dt>Ultimo tick completato</dt><dd>{world.last_tick}</dd>
          <dt>Politica produttiva</dt><dd>{world.policy}</dd>
          <dt>Prossimo tick (UTC)</dt><dd>{world.next_tick_at}</dd>
          <dt>Ora del server (UTC)</dt><dd>{world.server_time}</dd>
          <dt>Stato</dt><dd>{Date.parse(world.server_time) >= Date.parse(world.next_tick_at) ? "Recupero tick in corso" : "Operativo"}</dd>
        </dl>
      ) : <p role="status">Server temporaneamente non disponibile.</p>}
      <p>Ricarica la pagina per aggiornare lo stato.</p>
    </main>
  );
}
