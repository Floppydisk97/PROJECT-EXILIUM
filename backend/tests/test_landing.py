"""Landing, and the ground it opens.

Two claims are being tested. That a colony takes a tile once and for ever, with the database
refusing every way round it. And that what the tile says about itself really does shape the
ground -- because if it does not, choosing a landing site is a formality with a nice view.
"""
from uuid import uuid4

import psycopg
import pytest

from app import citygen
from app.db import transaction
from app.mapservice import generate_and_store
from app.service import DomainError, city_ground, land, provision

FREQUENCY = 12       # 1442 tiles: enough for coasts, rivers and several biomes


def world():
    with transaction() as conn:
        generate_and_store(conn, "Approdo", FREQUENCY)


def player(name="Exilium"):
    with transaction() as conn:
        return provision(conn, name)


def a_land_tile(biome=None, with_river=False):
    clause = "elevation >= 0 AND biome NOT IN ('ocean', 'lake', 'sea_ice')"
    if biome:
        clause += f" AND biome = '{biome}'"
    if with_river:
        clause += " AND river_flow > 0"
    with transaction() as conn:
        row = conn.execute(
            f"SELECT id FROM world_tiles WHERE map_id = 1 AND {clause} ORDER BY id LIMIT 1"
        ).fetchone()
    return None if row is None else row["id"]


def test_landing_takes_a_tile_and_rolls_the_ground(database):
    world()
    p = player()
    tile = a_land_tile()
    with transaction() as conn:
        result = land(conn, p["city_id"], p["player_id"], tile)
    assert result["tile_id"] == tile
    with transaction() as conn:
        row = conn.execute("SELECT tile_id, landed_at, map_seed FROM cities").fetchone()
    assert row["tile_id"] == tile and row["landed_at"] is not None
    assert len(row["map_seed"]) == 32


def test_a_colony_cannot_land_twice_or_move_afterwards(database):
    """Irreversible, and refused in two independent places. The rule says no; the trigger says
    no to anything that got past the rule. A constraint only the application enforces is one a
    future code path is free to forget."""
    world()
    p = player()
    first, second = a_land_tile(), None
    with transaction() as conn:
        rows = conn.execute(
            "SELECT id FROM world_tiles WHERE map_id = 1 AND elevation >= 0"
            " AND biome NOT IN ('ocean','lake','sea_ice') ORDER BY id LIMIT 2"
        ).fetchall()
    first, second = rows[0]["id"], rows[1]["id"]
    with transaction() as conn:
        land(conn, p["city_id"], p["player_id"], first)
    with pytest.raises(DomainError) as error, transaction() as conn:
        land(conn, p["city_id"], p["player_id"], second)
    assert error.value.detail == "already_landed"
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute("UPDATE cities SET tile_id = %s", (second,))


def test_two_colonies_cannot_share_a_tile(database):
    """The scarcity that makes a site worth choosing. There is one river in that desert."""
    world()
    first, second = player("A"), player("B")
    tile = a_land_tile()
    with transaction() as conn:
        land(conn, first["city_id"], first["player_id"], tile)
    # All three columns, so that what refuses this is the uniqueness of the tile and not the
    # all-or-nothing check standing in front of it.
    with pytest.raises(psycopg.errors.UniqueViolation), transaction() as conn:
        conn.execute(
            "UPDATE cities SET tile_id = %s, landed_at = now(), map_seed = %s WHERE id = %s",
            (tile, "f" * 32, second["city_id"]),
        )
    # ... and through the front door it is a refusal with a reason, not a crash.
    with pytest.raises(DomainError) as error, transaction() as conn:
        land(conn, second["city_id"], second["player_id"], tile)
    assert error.value.detail == "tile_taken"


def test_water_is_refused(database):
    world()
    p = player()
    with transaction() as conn:
        ocean = conn.execute(
            "SELECT id FROM world_tiles WHERE map_id = 1 AND biome = 'ocean' LIMIT 1"
        ).fetchone()["id"]
    with pytest.raises(DomainError) as error, transaction() as conn:
        land(conn, p["city_id"], p["player_id"], ocean)
    assert error.value.detail == "not_dry_land"


def test_the_ground_is_not_stored_and_comes_back_the_same_every_time(database):
    """The heart of it. Sixteen thousand cells a colony would be eighty million rows at the
    size this planet is built for; what is kept is a thirty-two character seed. Which is only
    sound if regenerating really does give the same place back."""
    world()
    p = player()
    with transaction() as conn:
        land(conn, p["city_id"], p["player_id"], a_land_tile())
    with transaction() as conn:
        first = city_ground(conn, p["city_id"], p["player_id"])
        second = city_ground(conn, p["city_id"], p["player_id"])
    assert first == second
    assert len(first["cells"]["ground"]) == first["size"] ** 2
    with transaction() as conn:
        # Nothing about those cells went anywhere near a table.
        tables = conn.execute(
            "SELECT count(*) AS n FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_name LIKE '%cell%'"
        ).fetchone()["n"]
    assert tables == 0


def test_two_colonies_on_identical_ground_get_different_maps(database):
    """Random at landing. The seed mixes the city, so the same tile twice -- which cannot
    happen now, but will the day a colony is abandoned -- is not the same map twice."""
    world()
    tile = a_land_tile()
    first = citygen.seed_for("Approdo", tile, uuid4())
    second = citygen.seed_for("Approdo", tile, uuid4())
    assert first != second
    # ... and a different world hands out different ground for the same tile and colony.
    city = uuid4()
    assert citygen.seed_for("Approdo", tile, city) != citygen.seed_for("Altrove", tile, city)


def test_an_unlanded_colony_has_no_ground(database):
    world()
    p = player()
    with pytest.raises(DomainError) as error, transaction() as conn:
        city_ground(conn, p["city_id"], p["player_id"])
    assert error.value.detail == "not_landed"


def test_the_biome_really_shapes_the_ground(database):
    """If this does not hold, choosing a landing site is a formality with a nice view.

    A swamp is mostly water and fertile; a desert is nearly all dry and barren. Asserted as an
    ordering rather than on exact numbers, because the numbers are balancing knobs in
    BIOME_RULES and are meant to be turned.
    """
    swamp = citygen.generate("x", citygen.Site("tropical_swamp", 40, 26.0, 2400, 0, False))
    desert = citygen.generate("x", citygen.Site("desert", 300, 31.0, 80, 0, False))
    ice = citygen.generate("x", citygen.Site("ice_sheet", 900, -30.0, 120, 0, False))

    assert desert.buildable > swamp.buildable * 3
    assert _mean(swamp.fertility) > _mean(desert.fertility) * 10
    assert _mean(ice.fertility) == 0
    assert _mean(swamp.vegetation) > _mean(desert.vegetation)


def test_a_river_makes_its_banks_worth_landing_on(database):
    """The one reason to land in a desert. Without it the site looked interesting on the
    planet and was worthless on the ground."""
    dry = citygen.generate("x", citygen.Site("desert", 300, 31.0, 80, 0, False))
    watered = citygen.generate("x", citygen.Site("desert", 300, 31.0, 80, 3100, False))
    assert max(watered.fertility) > 8 * max(dry.fertility)
    assert max(watered.vegetation) > 10 * max(dry.vegetation)
    # The bank is silt, not the sand the river crossed -- which is what stops the bonus being
    # halved by the biome's own ground right where it matters most.
    soil = citygen.GROUNDS.index("soil")
    assert soil in watered.ground and soil not in dry.ground


def _mean(values):
    return sum(values) / len(values)
