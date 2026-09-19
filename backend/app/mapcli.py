"""Local administration: generate the authoritative planet once. Never exposed as HTTP.

    docker compose exec api python -m app.mapcli

The seed defaults to worldgen.PRODUCTION_SEED: the deploy command used to carry it as a
literal, which is two places for one fact and no way to notice when they disagree.

Under MAP_BUILD=background this stands down unless asked with `--now`, so the same start
command that used to block for minutes returns at once and the API binds its port; the API
then spawns this module with `--now` to do the work. See app/mapbuild.py for why.
"""
import argparse
import json

from app import mapbuild, worldgen
from app.db import transaction
from app.mapservice import generate_and_store


def main():
    parser = argparse.ArgumentParser(description="Generate the singleton world map (one-shot)")
    parser.add_argument("seed", nargs="?", default=worldgen.PRODUCTION_SEED,
                        help="Deterministic generation seed; defaults to the shipped world")
    parser.add_argument("--frequency", type=int, default=worldgen.PRODUCTION_FREQUENCY,
                        help="Geodesic subdivision (2-160); the default seats far more than 5000 players")
    parser.add_argument("--now", action="store_true",
                        help="Build even under MAP_BUILD=background; this is how the API asks")
    args = parser.parse_args()
    if mapbuild.BACKGROUND and not args.now:
        print(json.dumps({"skipped": "MAP_BUILD=background; the API builds the map itself"}))
        return
    with transaction() as conn:
        summary = generate_and_store(conn, args.seed, args.frequency)
    print(json.dumps(summary, default=str))


if __name__ == "__main__":
    main()
