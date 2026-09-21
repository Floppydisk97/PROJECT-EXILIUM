"""The two roads to one planet must arrive at the same place.

`mapservice.read_map` reaches the drawn subset with SQL because at production size the
planner has to be steered; `mapexport` reaches it in Python because it has only a seed and no
database. Two routes to one answer is how this project has been bitten before -- the
continental field was written twice, identically, in two places, and nothing noticed when the
copies stopped agreeing. What makes the duplication safe here is that the agreement is
checked rather than assumed, and checked on the whole model rather than on a summary.
"""
import gzip
import json

import pytest
import math
from pathlib import Path

from app import mapexport, worldgen
from app.db import transaction
from app.mapservice import generate_and_store, read_map

FREQUENCY = 12   # 1442 tiles: big enough for coasts, lakes, rivers and a polar cap


def test_the_file_and_the_database_describe_the_same_planet(database):
    """The whole model, field by field. A summary (tile counts, land counts) would pass
    while the corner pool was ordered differently and every polygon came out wrong."""
    _store(worldgen.PRODUCTION_SEED)
    with transaction() as conn:
        from_database = read_map(conn)
    from_seed = mapexport.model_from_world(
        worldgen.generate(worldgen.PRODUCTION_SEED, FREQUENCY)
    )
    assert from_seed == from_database


def test_the_bytes_are_identical_too(database):
    """Equality of dicts is not equality of payloads: a float that serializes differently
    would pass the comparison above and still ship a different file."""
    _store(worldgen.PRODUCTION_SEED)
    with transaction() as conn:
        db_bytes = json.dumps(read_map(conn), separators=(",", ":")).encode()
    seed_bytes = json.dumps(
        mapexport.model_from_world(worldgen.generate(worldgen.PRODUCTION_SEED, FREQUENCY)),
        separators=(",", ":"),
    ).encode()
    assert seed_bytes == db_bytes


def test_rounding_is_not_cosmetic(database):
    """The database stores centres and corners already rounded. Building the model from raw
    generator floats would differ in the last decimals AND pool the corners differently,
    because corners are shared by exact value -- so every tile's ring would be wrong. This
    test exists because that is an easy line to delete while tidying."""
    world = worldgen.generate(worldgen.PRODUCTION_SEED, FREQUENCY)
    rows = mapexport._rows_from_world(world)
    for row in rows[:50]:
        assert row["cx"] == round(row["cx"], 4)
        for corner in row["polygon"]:
            assert corner == [round(c, 4) for c in corner]


def test_no_coordinate_is_negative_zero():
    """A tiny negative coordinate rounds to -0.0. It compares equal to 0.0 so nothing
    notices, but it serializes as "-0.0" while PostgreSQL hands the same value back as 0.0 --
    so the two models were equal as data and different as bytes. Corners are also pooled by
    exact value, so the two could have pooled differently. Ten appeared in a 1442-tile world;
    `math.copysign` is how you see one at all."""
    model = mapexport.model_from_world(
        worldgen.generate(worldgen.PRODUCTION_SEED, FREQUENCY)
    )
    for series in (model["corners"], model["tiles"]["center"]):
        assert not [c for c in series if c == 0.0 and math.copysign(1.0, c) < 0]


def test_export_writes_a_payload_and_a_manifest_that_names_it(tmp_path):
    """No database anywhere in this one: a seed is all it takes to rebuild the asset."""
    manifest = mapexport.export(tmp_path, worldgen.PRODUCTION_SEED, FREQUENCY)
    payload = tmp_path / manifest["file"]
    assert payload.exists()
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest
    assert manifest["seed"] == worldgen.PRODUCTION_SEED
    assert manifest["generator_version"] == worldgen.GENERATOR_VERSION
    assert manifest["tile_count"] == 10 * FREQUENCY**2 + 2

    model = json.loads(gzip.decompress(payload.read_bytes()))
    assert model["seed"] == worldgen.PRODUCTION_SEED
    assert model["tile_count"] == manifest["tile_count"]
    assert manifest["packed_bytes"] < manifest["raw_bytes"]


def test_the_name_follows_the_content(tmp_path):
    """The payload is cached forever by its name, so the name must change when the planet
    does -- otherwise a new world would be invisible behind an old cache entry."""
    first = mapexport.export(tmp_path, "Erebo-01", FREQUENCY)
    second = mapexport.export(tmp_path, "Erebo-02", FREQUENCY)
    assert first["file"] != second["file"]
    # ... and the old payload does not linger beside the new one.
    assert sorted(p.name for p in tmp_path.glob("planet-*.bin")) == [second["file"]]


def test_the_payload_is_not_named_gz(tmp_path):
    """Static hosts set Content-Encoding: gzip on a .gz name by guesswork; the browser would
    then unpack it silently and the client's own unpacking would fail on unpacked bytes.
    Exactly one party must be responsible for decompression."""
    manifest = mapexport.export(tmp_path, worldgen.PRODUCTION_SEED, FREQUENCY)
    assert not manifest["file"].endswith(".gz")


def _store(seed: str):
    with transaction() as conn:
        generate_and_store(conn, seed, FREQUENCY)


@pytest.mark.repo          # legge frontend/, che nell'immagine di prova non c'e'
def test_the_shipped_asset_describes_the_world_the_code_builds():
    """The viewer's planet is a committed file, so it can silently fall behind.

    A migration that resets the map changes the seed, the size or the generator, and the
    database gets the new world on the next deploy. The file does not: it only changes when
    someone remembers to run `python -m app.mapexport`. Forget, and the page shows one planet
    while the game runs another -- with nothing anywhere saying so.

    This is that "somebody remembers", written down. It fails on the change that causes the
    drift, not on the visit that discovers it.
    """
    manifest = json.loads(
        (Path(__file__).parents[2] / "frontend/public/map/manifest.json").read_text()
    )
    assert manifest["seed"] == worldgen.PRODUCTION_SEED
    assert manifest["frequency"] == worldgen.PRODUCTION_FREQUENCY
    assert manifest["generator_version"] == worldgen.GENERATOR_VERSION
    assert manifest["name"] == worldgen.WORLD_NAME
    assert manifest["tile_count"] == 10 * worldgen.PRODUCTION_FREQUENCY**2 + 2
    assert (Path(__file__).parents[2] / "frontend/public/map" / manifest["file"]).exists()
