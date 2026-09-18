"""Local administration: generate the authoritative planet once. Never exposed as HTTP.

    docker compose exec api python -m app.mapcli "Hesperia-seed"
"""
import argparse
import json

from app import worldgen
from app.db import transaction
from app.mapservice import generate_and_store


def main():
    parser = argparse.ArgumentParser(description="Generate the singleton world map (one-shot)")
    parser.add_argument("seed", help="Deterministic generation seed for the planet")
    parser.add_argument("--frequency", type=int, default=worldgen.PRODUCTION_FREQUENCY,
                        help="Geodesic subdivision (2-160); the default seats far more than 5000 players")
    args = parser.parse_args()
    with transaction() as conn:
        summary = generate_and_store(conn, args.seed, args.frequency)
    print(json.dumps(summary, default=str))


if __name__ == "__main__":
    main()
