"""Demo colony grounds as static files, so the viewer can draw one without a server.

The same trick the planet uses. The renderer takes a payload and draws it; whether that
payload came from a file baked at build time or from `GET /cities/{id}/ground` on a live API
is none of its business. Today there is no API in front of the viewer, so the ground is baked;
the day the game client exists it fetches the identical shape and nothing about the drawing
changes.

Several sites rather than one, because the whole claim being made is that the biome decides
the ground: a viewer that can only ever show one colony cannot show that at all.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from app import citygen, worldgen

COMPRESSION = 9

# Sites chosen to span the argument: what you land on changes what you get.
DEMOS = [
    ("delta",   "Delta tropicale",   citygen.Site("tropical_swamp", 40, 26.0, 2400, 2600, True)),
    ("nilo",    "Fiume nel deserto", citygen.Site("desert", 300, 31.0, 90, 3100, False)),
    ("foresta", "Foresta temperata", citygen.Site("temperate_forest", 220, 12.0, 1100, 900, False)),
    ("costa",   "Costa boreale",     citygen.Site("boreal_forest", 90, 2.0, 800, 0, True)),
    ("altopiano", "Altopiano arido", citygen.Site("arid_shrubland", 1500, 18.0, 240, 0, False)),
    ("ghiaccio", "Calotta polare",   citygen.Site("ice_sheet", 600, -28.0, 150, 0, False)),
]


def payload(name: str, label: str, site: citygen.Site, seed: str) -> dict:
    ground = citygen.generate(seed, site)
    return {
        "name": name, "label": label, "seed": ground.seed, "size": ground.size,
        "cell_metres": ground.cell_metres, "buildable": ground.buildable,
        "site": {
            "biome": site.biome, "elevation": site.elevation, "temperature": site.temperature,
            "rainfall": site.rainfall, "river_flow": site.river_flow, "coastal": site.coastal,
        },
        "ground_names": list(ground.ground_names),
        "cells": {
            "ground": list(ground.ground), "height": list(ground.height),
            "fertility": list(ground.fertility), "vegetation": list(ground.vegetation),
        },
    }


def export(directory: Path, world_seed: str) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("colony-*.bin"):
        stale.unlink()

    entries = []
    for index, (name, label, site) in enumerate(DEMOS):
        seed = citygen.seed_for(world_seed, index, f"demo-{name}")
        body = json.dumps(payload(name, label, site, seed), separators=(",", ":")).encode()
        packed = gzip.compress(body, COMPRESSION)
        digest = hashlib.sha256(body).hexdigest()[:12]
        filename = f"colony-{name}-{digest}.bin"
        (directory / filename).write_bytes(packed)
        entries.append({
            "name": name, "label": label, "file": filename, "biome": site.biome,
            "size": citygen.SIZE, "packed_bytes": len(packed), "raw_bytes": len(body),
        })

    manifest = {"world_seed": world_seed, "colonies": entries}
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Bake demo colony grounds for the viewer.")
    parser.add_argument("--out", type=Path, default=Path("frontend/public/colony"))
    parser.add_argument("--seed", default=worldgen.PRODUCTION_SEED)
    args = parser.parse_args()
    manifest = export(args.out, args.seed)
    for entry in manifest["colonies"]:
        print(f"{entry['label']:<20} {entry['packed_bytes'] / 1024:>7.0f} KB  {entry['file']}")


if __name__ == "__main__":
    main()
