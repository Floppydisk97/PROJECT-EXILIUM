"""Fill in the ground of colonies that landed before the ground was worth anything.

    python -m app.sitefill [--yes]

Ruleset 2 gave a colony three numbers taken from its own map. Colonies that landed under
ruleset 1 have none, and the rules read that as "no ground", which keeps them producing
exactly as they did -- correct, but not what they are standing on.

The backfill is EXACT rather than a guess, and that is the whole point of having stored a
seed: the map is a pure function of the seed and of what the planet says about the site, and
both are still there. Nothing is approximated and nothing is lost.

It costs a few seconds per colony, because it grows the real map at its real size. That is
why it is a command run once and not something the server does while somebody waits.
"""
from __future__ import annotations

import argparse
import sys

from app import citygen
from app.db import transaction
from app.service import _site_of


def pending(conn) -> list:
    return conn.execute(
        """SELECT id, name, tile_id, map_seed FROM cities
           WHERE tile_id IS NOT NULL AND site_yield IS NULL
           ORDER BY landed_at"""
    ).fetchall()


def measure(conn, row) -> citygen.SiteEconomy:
    """Grow the colony's real map and reduce it. Reads only -- deciding is `main`'s job."""
    site, _tile = _site_of(conn, row["tile_id"])
    return site.biome, citygen.generate(row["map_seed"], site).economy


def store(conn, city_id, economy) -> None:
    conn.execute(
        "UPDATE cities SET site_yield = %s, site_effort = %s, site_room = %s WHERE id = %s",
        (economy.yield_, economy.effort, economy.room, city_id),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true",
                        help="apply; without it, say what would be filled and change nothing")
    args = parser.parse_args()

    with transaction() as conn:
        rows = pending(conn)
    if not rows:
        print("Nessuna colonia da riempire.")
        return 0

    print(f"{len(rows)} colonie atterrate senza terreno"
          f"{'.' if args.yes else ' -- prova a vuoto, usa --yes per applicare.'}")
    for row in rows:
        # One transaction per colony: growing a map takes seconds, which is long enough that
        # holding every other row meanwhile would be rude, and a failure on one colony must
        # not undo the ones already filled.
        with transaction() as conn:
            biome, economy = measure(conn, row)
            if args.yes:
                store(conn, row["id"], economy)
        print(f"  {row['name']:20} {biome:22} resa {economy.yield_:3d}"
              f"  fatica {economy.effort:3d}  spazio {economy.room}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
