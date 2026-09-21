"""Building the planet without holding the front door shut.

The map is generated once, and generating it is minutes of CPU. Until now that work sat in
the service's start command, before `exec uvicorn` -- so the port stayed closed for the whole
build. That was survivable while the planet was small and the instance had CPU credit to
burn; it stopped being survivable the day both changed:

    193 212 caselle, con burst di CPU        13 s
    231 042 caselle, senza burst          6 min 30 s   "Port scan timeout reached"
    231 042 caselle, credito esaurito      >27 min     esito ignoto

Render watches for an open port and gives up if one never appears, so at 0,15 of a core that
arrangement is a bet, not a design. Here the bet is removed: the server binds immediately and
the planet is built afterwards, by a separate process.

Why a subprocess rather than a thread: generation peaks around 370 MB and Python hands very
little of that back to the allocator when it finishes. A child process gives all of it back
to the operating system by exiting, which on a 512 MB instance is the difference between a
brief peak and a permanently fat server.

The cost, stated plainly: while the child runs, the server (~60 MB) and the build (~370 MB)
are alive together, so the peak goes from ~377 MB to ~430 MB of the 512 available. The margin
drops from ~134 MB to ~80. It is a one-shot cost, paid once per world.
"""
import json
import os
import subprocess
import sys
import threading

# Set on the service to move generation off the start command. Anything else -- including
# the variable being absent -- keeps the old behaviour, so a deployment that has not been
# told about this change behaves exactly as it did before.
BACKGROUND = os.environ.get("MAP_BUILD") == "background"

_started = threading.Lock()
_done = False


def map_is_missing(conn) -> bool:
    return conn.execute("SELECT 1 FROM world_map WHERE id = 1").fetchone() is None


def map_identity(conn) -> dict | None:
    """Di QUALE pianeta ha in pancia questo database.

    Serve perche' il pianeta esiste in due posti -- la tabella, che decide dove si atterra, e
    il file spedito col visore, che decide cosa si vede -- e finora nessuno li confrontava. Il
    test che esiste mette a confronto il file e il CODICE; il database era la terza copia, e
    una terza copia che nessuno guarda e' esattamente come le altre sei divergenze di questo
    progetto. Scritto nel log all'avvio, cosi' la domanda ha una risposta senza aprire niente.
    """
    row = conn.execute(
        "SELECT name, seed, frequency, generator_version FROM world_map WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    tiles = conn.execute("SELECT count(*) AS n FROM world_tiles").fetchone()["n"]
    return {**dict(row), "tile_count": int(tiles)}


def start_background_build() -> str:
    """Spawn the generator and return immediately. Never raises: a world that fails to build
    must not also take down a server that is otherwise healthy and able to say so."""
    global _done
    if not BACKGROUND:
        return "disabled"
    with _started:
        if _done:
            return "already started"
        _done = True

    try:
        from app.db import transaction
        with transaction() as conn:
            if not map_is_missing(conn):
                # L'identita' del pianeta e' DIAGNOSTICA, e la diagnostica non decide: se
                # leggerla fallisce, il mondo c'e' lo stesso e il servizio deve poterlo dire.
                # Un test esistente difendeva proprio questo, e la prima versione lo ha rotto.
                try:
                    print(json.dumps({"planet": map_identity(conn)}, default=str), flush=True)
                except Exception as error:              # noqa: BLE001 - riportato, mai fatale
                    print(f"[mapbuild] planet identity unavailable: {error!r}", flush=True)
                return "map already present"
    except Exception as error:                      # noqa: BLE001 - reported, never fatal
        print(f"[mapbuild] could not check for a map: {error!r}", flush=True)
        return "check failed"

    # `--now` is what tells the child to do the work: without it `mapcli` stands down under
    # MAP_BUILD=background, which is exactly what makes the start command return at once.
    #
    # The child inherits this process's stdout and stderr so that whether the world was built
    # ends up in the service log. The first version sent both to DEVNULL, and the cost of that
    # showed up the same day: asked whether the planet had been generated, the only honest
    # answer was that a process had been started and then silenced. `start_new_session` is what
    # detaches it; muting it was never part of the job.
    try:
        subprocess.Popen(
            [sys.executable, "-m", "app.mapcli", "--now"],
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except Exception as error:                      # noqa: BLE001
        print(f"[mapbuild] could not start the generator: {error!r}", flush=True)
        return "spawn failed"
    print(json.dumps({"mapbuild": "started", "detached": True}), flush=True)
    return "started"
