"""The planet as a file, so that looking at it needs no server.

The viewer asks the API for exactly two things: the map, which is immutable and generated
once, and a decorative tick pill. Everything else -- cities, orders, ledger -- needs a token
and the public page never touches it. So the whole of a day spent on cold starts, 502s, 429s
and instance hours went into delivering a 4 MB file that never changes.

Written to disk and served as a static asset, that file needs no instance to wake up, cannot
answer 502, and costs nothing to host. It is also the shape the game wants anyway: a
downloadable client ships its world as data, not as a network call.

WHY THIS BUILDS THE MODEL A SECOND WAY. `mapservice.read_map` reaches the drawn subset with
SQL, deliberately: at production size the planner has to be steered, and there is a long
comment there about it. That path needs a database holding the world. Here there is only a
seed, so the same subset is reached in Python.

Two routes to one answer is how this project has been bitten before -- the continental field
was defined twice, identically, until the two copies stopped agreeing. The difference is that
this time the agreement is a test: `test_mapexport.py` generates a world, stores it, and
requires the two models to be *identical*. Drift becomes a failure instead of a wrong planet.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from app import mapservice, worldgen

# gzip level 9 rather than the 6 the API serves. The API compresses on every cold process
# and cares about the CPU; this runs once per world, by hand, so it can afford the best.
COMPRESSION = 9


def _rows_from_world(world: worldgen.World) -> list[dict]:
    """The drawn subset, in the shape `build_model` reads, sorted by id.

    The rule is the SQL one, stated in Python: land, the sea ice that makes the polar caps
    read as caps, and one ring of ocean around every coast -- the shelf that stops continents
    looking like plates dropped on flat blue. Open ocean past that ring is a smooth shell on
    the client and its polygons would be dead weight.

    Rounding matters and is not cosmetic: the database stores centres and polygon corners
    already rounded by `_tile_rows`, so a model built from raw generator floats would differ
    in the last decimals -- and, worse, would pool corners differently, because corners are
    shared by exact value. The same `_round` is applied here for that reason.
    """
    shelf: set[int] = set()
    water = set()
    for tile in world.tiles:
        if tile.elevation >= 0:
            shelf.update(tile.neighbors)
        if tile.biome in ("ocean", "sea_ice"):
            water.add(tile.id)

    rows = []
    for tile in world.tiles:
        drawn = (tile.elevation >= 0 or tile.biome == "sea_ice") or (
            tile.elevation < 0 and tile.biome == "ocean" and tile.id in shelf
        )
        if not drawn:
            continue
        cx, cy, cz = mapservice._round(tile.center)
        rows.append({
            "id": tile.id, "cx": cx, "cy": cy, "cz": cz,
            "elevation": tile.elevation, "temperature": tile.temperature,
            "rainfall": tile.rainfall, "biome": tile.biome,
            "river_flow": tile.river_flow, "landmass_size": tile.landmass_size,
            "neighbor_count": len(tile.neighbors),
            "coastal": any(n in water for n in tile.neighbors),
            "polygon": [mapservice._round(p) for p in tile.polygon],
        })
    rows.sort(key=lambda row: row["id"])
    return rows


def _rivers_from_world(world: worldgen.World) -> dict:
    """The reaches, matching `_river_columns`' SQL exactly.

    A lake tile is never the source of a reach: it sits at its water surface so it passes the
    elevation test, and it carries everything its basin collected so it passes the flow test
    -- which drew a river straight across the middle of the lake. The reach that *ends* in
    the lake is kept, so a river still reaches the shore.

    A tile whose downstream is -1 (ocean, or a basin with no outlet) is dropped, which is
    what the SQL join does by finding no row to join to.
    """
    by_id = {tile.id: tile for tile in world.tiles}
    threshold = worldgen.river_min_flow(len(world.tiles))
    a: list[float] = []
    b: list[float] = []
    flow: list[int] = []
    ae: list[int] = []
    be: list[int] = []
    for tile in sorted(world.tiles, key=lambda t: t.id):
        if tile.elevation < 0 or tile.biome == "lake" or tile.river_flow < threshold:
            continue
        down = by_id.get(tile.downstream)
        if down is None:
            continue
        a += mapservice._round(tile.center)
        b += mapservice._round(down.center)
        flow.append(tile.river_flow)
        ae.append(tile.elevation)
        be.append(max(0, down.elevation))
    return {"a": a, "b": b, "flow": flow, "ae": ae, "be": be}


def model_from_world(world: worldgen.World) -> dict:
    """The same render model `read_map` returns, without a database anywhere near it."""
    meta = {
        "name": worldgen.WORLD_NAME, "seed": world.seed,
        "frequency": world.frequency, "sea_level": world.sea_level,
    }
    return mapservice.build_model(
        meta, _rows_from_world(world), len(world.tiles), _rivers_from_world(world)
    )


def export(directory: Path, seed: str, frequency: int) -> dict:
    """Write the planet and a manifest naming it. Returns what was written.

    The payload's name carries a hash of its content, so a browser may cache it forever and
    a new world simply has a new name. The manifest is the only file fetched unconditionally,
    and it is a few hundred bytes -- which is what makes the staleness question disappear
    rather than be managed.

    The file is NOT named `.gz`. Static hosts set `Content-Encoding: gzip` on that extension
    by guesswork, the browser would then decompress it silently, and the client's own
    decompression would fail on bytes already unpacked. A neutral extension keeps exactly one
    party responsible for unpacking.
    """
    world = worldgen.generate(seed, frequency)
    model = model_from_world(world)
    raw = json.dumps(model, separators=(",", ":")).encode()
    packed = gzip.compress(raw, COMPRESSION)
    digest = hashlib.sha256(raw).hexdigest()[:12]
    name = f"planet-{digest}.bin"

    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("planet-*.bin"):
        stale.unlink()   # one world at a time; an orphan would just be dead weight in git
    (directory / name).write_bytes(packed)

    manifest = {
        "file": name,
        "name": model["name"],
        "seed": model["seed"],
        "frequency": model["frequency"],
        "generator_version": worldgen.GENERATOR_VERSION,
        "tile_count": model["tile_count"],
        "land_count": model["land_count"],
        "raw_bytes": len(raw),
        "packed_bytes": len(packed),
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the planet as a static asset.")
    parser.add_argument("--out", type=Path, default=Path("frontend/public/map"),
                        help="directory to write the payload and its manifest into")
    parser.add_argument("--seed", default=worldgen.PRODUCTION_SEED)
    parser.add_argument("--frequency", type=int, default=worldgen.PRODUCTION_FREQUENCY)
    args = parser.parse_args()
    print(json.dumps(export(args.out, args.seed, args.frequency), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
