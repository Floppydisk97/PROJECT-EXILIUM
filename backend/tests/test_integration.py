"""The continuous world against a real PostgreSQL.

The tick is gone, and with it the shape most of these tests used to have: no boundary to
cross, no queue to drain, no barrier to contend for. What replaced it is a world where
production accrues from timestamps, a commitment completes at the moment it is due, and a
city is brought up to date whenever somebody looks at it -- under a lock on that city alone.

These tests are about the seam, not the rules: locking, idempotency, the clock, and the
constraints the database is asked to enforce on its own.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from fastapi.testclient import TestClient

from app import db, service
from app.db import database_now, transaction
from app.main import app
from app.mapservice import generate_and_store, read_map
from app.service import (
    DomainError, balance, cast_vote, current_policy, land, provision, read_city, start_upgrade,
)
from app.sim.config import RULESET, upgrade_cost, upgrade_duration
from app.worker import sweep


def player(name="Exilium"):
    with transaction() as conn:
        return provision(conn, name)


def rewind(seconds):
    """Move every city's cursor into the past, so that production has accrued.

    The clock replacement for `age_world`. There is no boundary to age a world past any more:
    what makes something happen is elapsed time, so the way to make a test's world old is to
    say its cities were settled a while ago. The policy timeline is dragged back with them,
    because settling across a stretch no period covers is refused rather than paid as nothing.
    """
    with transaction() as conn:
        conn.execute(
            """UPDATE cities SET created_at = created_at - make_interval(secs => %s),
                                 settled_at = settled_at - make_interval(secs => %s)""",
            (seconds, seconds),
        )
        conn.execute(
            "UPDATE policy_periods SET from_at = LEAST(from_at,"
            " (SELECT min(settled_at) FROM cities))"
        )


def freeze_clock(monkeypatch):
    """Pin the clock so setup never straddles a whole-second boundary and mints stray
    production. Returns the instant everything is pinned to."""
    with transaction() as conn:
        now = database_now(conn)
    # One seam, patched in one place. `service` and `worker` both reach the clock through
    # `db`, rather than each binding their own copy of it at import -- which is what made a
    # sweep silently keep using the real time while everything else was frozen.
    monkeypatch.setattr(db, "database_now", lambda conn: now)
    return now


def test_migration_rerun_and_world_singleton(database):
    command.upgrade(database, "head")
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM world").fetchone()["n"] == 1
        # Exactly one policy period is open: a world with none cannot settle anybody, and a
        # world with two would pay the same seconds twice.
        assert conn.execute(
            "SELECT count(*) AS n FROM policy_periods WHERE to_at IS NULL"
        ).fetchone()["n"] == 1
    # Columns named rather than positional. A bare SELECT stops testing the singleton the day
    # the world grows a NOT NULL column: the copy leaves it null and the insert fails on that
    # instead, which looks like a pass and proves nothing about `CHECK (id = 1)`.
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute(
            """INSERT INTO world (id, time_speed, time_anchor_real, time_anchor_world)
               SELECT 2, time_speed, time_anchor_real, time_anchor_world FROM world"""
        )


def test_an_upgrade_spends_now_and_arrives_later(database, monkeypatch):
    """The shape of the whole change. The alloy goes at once -- committing is spending -- and
    the level turns up when the time has actually passed, not at a boundary."""
    now = freeze_clock(monkeypatch)
    p = player()
    with transaction() as conn:
        commitment = start_upgrade(conn, p["city_id"], p["player_id"], uuid4())
    assert commitment["completes_at"] == now + upgrade_duration(0)
    with transaction() as conn:
        # Paid, but not yet arrived.
        assert balance(conn, p["city_id"]) == 100_000 - upgrade_cost(0)
        assert conn.execute("SELECT level FROM cities").fetchone()["level"] == 0
        view = read_city(conn, p["city_id"], p["player_id"])
    assert view["busy_until"] == commitment["completes_at"] and view["busy_with"] == "upgrade"

    # ... and once the moment has passed, simply looking is enough to make it real.
    monkeypatch.setattr(db, "database_now", lambda conn: now + upgrade_duration(0))
    with transaction() as conn:
        view = read_city(conn, p["city_id"], p["player_id"])
    assert view["level"] == 1 and view["busy_until"] is None


def test_a_busy_city_cannot_start_a_second_thing(database, monkeypatch):
    """The new scarcity, and it is enforced twice on purpose: the rules say no, and the
    database would refuse anyway. A constraint that only the application enforces is a
    constraint that a future code path gets to forget about."""
    freeze_clock(monkeypatch)
    p = player()
    with transaction() as conn:
        start_upgrade(conn, p["city_id"], p["player_id"], uuid4())
    with pytest.raises(DomainError) as error, transaction() as conn:
        start_upgrade(conn, p["city_id"], p["player_id"], uuid4())
    assert (error.value.status, error.value.detail) == (409, "already_busy")
    with pytest.raises(psycopg.errors.UniqueViolation), transaction() as conn:
        conn.execute(
            """INSERT INTO orders(city_id, idempotency_key, kind, submitted_at, completes_at)
               VALUES (%s, %s, 'upgrade', now(), now() + interval '1 hour')""",
            (p["city_id"], uuid4()),
        )


def test_a_retried_commitment_spends_only_once(database, monkeypatch):
    freeze_clock(monkeypatch)
    p = player()
    key = uuid4()
    with transaction() as conn:
        first = start_upgrade(conn, p["city_id"], p["player_id"], key)
    with transaction() as conn:
        second = start_upgrade(conn, p["city_id"], p["player_id"], key)
        assert balance(conn, p["city_id"]) == 100_000 - upgrade_cost(0)
    assert second["id"] == first["id"]


def test_the_sweeper_finishes_what_nobody_is_watching(database, monkeypatch):
    """A shared world has to be true for the people who are not looking at your city. The
    sweep is not required for correctness -- a city is right the moment it is read -- but the
    written-down world should not drift far behind the real one."""
    now = freeze_clock(monkeypatch)
    p = player()
    with transaction() as conn:
        start_upgrade(conn, p["city_id"], p["player_id"], uuid4())
    assert sweep() == 0                                   # nothing is due yet
    monkeypatch.setattr(db, "database_now", lambda conn: now + upgrade_duration(0))
    assert sweep() == 1
    with transaction() as conn:
        assert conn.execute("SELECT level FROM cities").fetchone()["level"] == 1
        assert conn.execute("SELECT status FROM orders").fetchone()["status"] == "applied"
    assert sweep() == 0                                   # and it does not do it twice


def test_competing_sweeps_complete_a_commitment_once(database, monkeypatch):
    now = freeze_clock(monkeypatch)
    p = player()
    with transaction() as conn:
        start_upgrade(conn, p["city_id"], p["player_id"], uuid4())
    monkeypatch.setattr(db, "database_now", lambda conn: now + upgrade_duration(0))
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: sweep(), range(4))) == 1
    with transaction() as conn:
        assert conn.execute("SELECT level FROM cities").fetchone()["level"] == 1


def test_a_policy_change_does_not_repay_the_past(database, monkeypatch):
    """The reason policy is a timeline instead of a column.

    A city that has not been settled for a while, and a policy that changed in the middle of
    that while, must be paid the old rate for the old seconds. The tick used to guarantee it
    by settling everybody at the boundary -- a global barrier. Here the city works its own
    history out, and this is the assertion that says it really does.
    """
    p = player()
    rewind(60)
    with transaction() as conn:
        cast_vote(conn, p["city_id"], p["player_id"], "industrial")
        assert current_policy(conn) == "industrial"
    with transaction() as conn:
        view = read_city(conn, p["city_id"], p["player_id"])
    earned = int(view["alloy_milli"]) - 100_000
    # Sixty seconds at 10/s is 600; sixty at 20/s would be 1200. The truth is in between,
    # because the switch happened partway: anything outside that band means the timeline was
    # ignored in one direction or the other.
    assert 600 <= earned < 1200, earned


def test_the_majority_is_continuous_and_a_tie_keeps_the_incumbent(database):
    first, second, third = player("A"), player("B"), player("C")
    with transaction() as conn:
        assert current_policy(conn) == "balanced"
        # Abstentions do not count -- the majority is of the votes CAST, which is the rule the
        # tick's election already had and which this change deliberately did not touch. One
        # voter in a silent world therefore decides; worth knowing, and not decided here.
        result = cast_vote(conn, first["city_id"], first["player_id"], "industrial")
    assert result["policy"] == "industrial"
    with transaction() as conn:
        # A tie keeps what is in force rather than flipping back.
        cast_vote(conn, second["city_id"], second["player_id"], "balanced")
        assert current_policy(conn) == "industrial"
    with transaction() as conn:
        cast_vote(conn, third["city_id"], third["player_id"], "balanced")
        assert current_policy(conn) == "balanced"


def test_the_timeline_records_a_move_and_collapses_one_that_took_no_time(database, monkeypatch):
    """Two assertions about the same invariant: a period has positive length.

    Changes seconds apart leave a record of what was in force when. Changes inside one second
    leave ONE period, because a stretch of zero length covers no production and could not be
    told apart from the one it replaced -- and, left alone, it would collide with the
    uniqueness of `from_at` and fail the request outright.
    """
    first, second = player("A"), player("B")
    now = freeze_clock(monkeypatch)
    with transaction() as conn:
        cast_vote(conn, first["city_id"], first["player_id"], "industrial")
        cast_vote(conn, second["city_id"], second["player_id"], "industrial")
    with transaction() as conn:
        collapsed = conn.execute("SELECT policy FROM policy_periods ORDER BY from_at").fetchall()
    assert [p["policy"] for p in collapsed] == ["industrial"]

    monkeypatch.setattr(db, "database_now", lambda conn: now + timedelta(seconds=30))
    with transaction() as conn:
        cast_vote(conn, first["city_id"], first["player_id"], "balanced")
        cast_vote(conn, second["city_id"], second["player_id"], "balanced")
    with transaction() as conn:
        periods = conn.execute(
            "SELECT policy, from_at, to_at FROM policy_periods ORDER BY from_at"
        ).fetchall()
    assert [p["policy"] for p in periods] == ["industrial", "balanced"]
    assert periods[0]["to_at"] == periods[1]["from_at"] == now + timedelta(seconds=30)
    assert periods[1]["to_at"] is None


@pytest.mark.parametrize("statement", [
    "UPDATE resource_ledger SET amount=1",
    "DELETE FROM resource_ledger",
    "TRUNCATE resource_ledger",
])
def test_audit_tables_are_immutable(database, statement):
    player()
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute(statement)


def test_an_unaffordable_upgrade_has_no_partial_effects(database, monkeypatch):
    freeze_clock(monkeypatch)
    p = player()
    with transaction() as conn:
        service.entry(conn, p["city_id"], -100000, "upgrade", "fixture-spend", database_now(conn))
    with pytest.raises(DomainError) as error, transaction() as conn:
        start_upgrade(conn, p["city_id"], p["player_id"], uuid4())
    assert error.value.detail == "insufficient_alloy"
    with transaction() as conn:
        assert balance(conn, p["city_id"]) == 0
        assert conn.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0


def test_api_authorization_validation_idempotency_and_ledger(database):
    p, other = player(), player("Other")
    headers = {"Authorization": f"Bearer {p['token']}", "Idempotency-Key": str(uuid4())}
    path = f"/cities/{p['city_id']}"
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert client.get(f"/cities/{other['city_id']}", headers=headers).status_code == 404
        assert client.post(f"/cities/{other['city_id']}/upgrade", headers=headers).status_code == 404
        # The idempotency key is required, not optional.
        assert client.post(path + "/upgrade",
                           headers={"Authorization": headers["Authorization"]}).status_code == 422
        assert client.put(path + "/vote", headers=headers, json={"choice": "sideways"}).status_code == 422
        assert client.put(path + "/vote", headers=headers, json={"choice": "industrial"}).status_code == 200

        first = client.post(path + "/upgrade", headers=headers)
        second = client.post(path + "/upgrade", headers=headers)
        assert first.status_code == 200 and second.json() == first.json()
        # A second, different key is refused while the city is busy -- not queued.
        busy = client.post(path + "/upgrade",
                           headers={**headers, "Idempotency-Key": str(uuid4())})
        assert busy.status_code == 409 and busy.json()["detail"] == "already_busy"

        state = client.get(path, headers=headers).json()
        ledger = client.get(path + "/ledger", headers=headers).json()
        assert int(state["alloy_milli"]) == sum(int(row["amount"]) for row in ledger)
        assert state["busy_with"] == "upgrade"
        assert client.get(path + "/ledger?limit=201", headers=headers).status_code == 422
        assert client.get(path + "/commitments", headers=headers).json()[0]["id"] == first.json()["id"]
        # Every ledger row records which rules produced it, now that no tick does.
        assert all(row["ruleset"] == RULESET for row in ledger)


def test_simultaneous_reads_never_duplicate_production(database, monkeypatch):
    p = player()
    rewind(37)
    freeze_clock(monkeypatch)

    def read(_):
        with transaction() as conn:
            return read_city(conn, p["city_id"], p["player_id"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        views = list(pool.map(read, range(4)))
    assert {view["alloy_milli"] for view in views} == {"100370"}
    with transaction() as conn:
        assert conn.execute(
            "SELECT count(*) AS n FROM resource_ledger WHERE reason='production'"
        ).fetchone()["n"] == 1


def test_distinct_cities_settle_concurrently_without_any_global_lock(database, monkeypatch):
    """This used to be true *between* ticks and false during one. With the barrier gone it is
    simply true: nothing in the economic path takes a lock on anything shared."""
    first, second = player("A"), player("B")
    rewind(60)
    freeze_clock(monkeypatch)

    def read(p):
        with transaction() as conn:
            return read_city(conn, p["city_id"], p["player_id"])

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(read, [first, second, first, second, first, second]))
    with transaction() as conn:
        for p in (first, second):
            n = conn.execute(
                "SELECT count(*) AS n FROM resource_ledger WHERE city_id=%s AND reason='production'",
                (p["city_id"],),
            ).fetchone()["n"]
            assert n == 1                       # 60s at rate 10 -> one entry, no duplicates
            assert balance(conn, p["city_id"]) == 100000 + 600


def test_materialized_balance_equals_ledger_sum(database, monkeypatch):
    first, second = player("A"), player("B")
    rewind(120)
    now = freeze_clock(monkeypatch)
    with transaction() as conn:
        start_upgrade(conn, first["city_id"], first["player_id"], uuid4())
    monkeypatch.setattr(db, "database_now", lambda conn: now + upgrade_duration(0))
    sweep()
    with transaction() as conn:
        read_city(conn, second["city_id"], second["player_id"])
        cities = conn.execute("SELECT id, balance_milli FROM cities ORDER BY id").fetchall()
        for city in cities:
            ledger_sum = int(conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS s FROM resource_ledger WHERE city_id = %s",
                (city["id"],),
            ).fetchone()["s"])
            assert int(city["balance_milli"]) == ledger_sum
            assert balance(conn, city["id"]) == ledger_sum
            assert ledger_sum > 0
def test_ledger_enforces_no_overdraft_and_duplicate_event(database):
    p = player()
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        service.entry(conn, p["city_id"], -100001, "upgrade", "bad-debit", database_now(conn))
    with pytest.raises(psycopg.errors.UniqueViolation), transaction() as conn:
        service.entry(conn, p["city_id"], 1, "genesis", f"genesis:{p['city_id']}", database_now(conn))


def test_materialized_balance_rejects_overdraft_without_scanning_ledger(database):
    p = player()
    with transaction() as conn:
        service.entry(conn, p["city_id"], -100000, "upgrade", "spend-all", database_now(conn))
        assert balance(conn, p["city_id"]) == 0
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        service.entry(conn, p["city_id"], -1, "upgrade", "overdraft", database_now(conn))
    with transaction() as conn:
        assert int(conn.execute(
            "SELECT balance_milli FROM cities WHERE id = %s", (p["city_id"],)
        ).fetchone()["balance_milli"]) == 0


def test_world_map_generates_persists_and_is_immutable(database):
    with transaction() as conn:
        summary = generate_and_store(conn, "Church", frequency=6)
    assert summary["tiles"] == 362 and summary["name"] == "Hesperia"
    with transaction() as conn:
        world = read_map(conn)
    assert world["tile_count"] == 362 and world["frequency"] == 6
    columns = world["tiles"]
    count = len(columns["id"])
    assert count > 0
    # Columns are parallel: one entry per tile, three numbers per vector, and the ring
    # offsets bracket every tile's corners.
    for name in ("elevation", "temperature", "rainfall", "biome", "river_flow",
                 "landmass_size", "neighbor_count"):
        assert len(columns[name]) == count, name
    assert len(columns["center"]) == 3 * count
    assert len(columns["ring_offset"]) == count + 1
    assert columns["ring_offset"][-1] == len(columns["ring"])

    names = world["biome_names"]
    # Every corner index points into the shared pool, and every cell is a pentagon or hexagon.
    corner_count = len(world["corners"]) // 3
    assert all(0 <= i < corner_count for i in columns["ring"])
    for t in range(count):
        span = columns["ring_offset"][t + 1] - columns["ring_offset"][t]
        assert span in (5, 6)
    # The render model carries land, the polar sea ice and the shelf ring around every
    # coast -- never the open ocean beyond it.
    assert any(e >= 0 for e in columns["elevation"])
    for t in range(count):
        if columns["elevation"][t] >= 0:
            continue
        assert names[columns["biome"][t]] in ("sea_ice", "ocean")
    # What the flat map does not read, the map does not carry: the terrain normals and the
    # relief exaggeration went with the extruded terrain they were computed for.
    assert "normal" not in columns
    assert "relief_gain" not in world and "elevation_max" not in world
    rivers = world["rivers"]
    assert len(rivers["a"]) == len(rivers["b"]) == 3 * len(rivers["flow"])
    # One-shot: a second generation is refused, never a silent overwrite.
    with pytest.raises(DomainError) as error, transaction() as conn:
        generate_and_store(conn, "Church", frequency=6)
    assert error.value.status == 409
    # Tiles and map are immutable audit geography.
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute("UPDATE world_tiles SET biome = 'desert'")
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute("DELETE FROM world_map")


def test_world_map_endpoint_serves_geography_or_404(database):
    with TestClient(app) as client:
        # Before generation: 404, not an empty map.
        assert client.get("/world/map").status_code == 404
        with transaction() as conn:
            generate_and_store(conn, "Church", frequency=6)
        body = client.get("/world/map").json()
        assert body["tile_count"] == 362 and body["name"] == "Hesperia"
        assert body["land_count"] <= body["tile_count"]


def test_world_map_is_cached_and_revalidates(database):
    with TestClient(app) as client:
        with transaction() as conn:
            generate_and_store(conn, "Church", frequency=6)
        first = client.get("/world/map")
        assert first.status_code == 200
        etag = first.headers["ETag"]
        # Immutable geography may be cached; live state elsewhere may not.
        assert "immutable" in first.headers["Cache-Control"]
        assert client.get("/world").headers["Cache-Control"] == "no-store"

        # A second call is served from the process cache: same bytes, same tag.
        second = client.get("/world/map")
        assert second.headers["ETag"] == etag
        assert second.content == first.content

        # And a client that already has it gets told so instead of the payload again.
        revalidated = client.get("/world/map", headers={"If-None-Match": etag})
        assert revalidated.status_code == 304
        assert revalidated.content == b""


def test_rate_limit_counts_per_address_and_spares_health():
    from app.main import RATE_LIMIT, _rate, over_rate_limit

    _rate.clear()
    try:
        assert not any(over_rate_limit("1.2.3.4") for _ in range(RATE_LIMIT))
        assert over_rate_limit("1.2.3.4")          # the next one is refused
        assert not over_rate_limit("5.6.7.8")      # a different caller is unaffected
    finally:
        _rate.clear()

    # Health checks bypass the limit entirely: Render polls them from one address and a
    # throttled health check would take the service down.
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200


def test_two_colonies_on_different_ground_do_not_earn_the_same(database, monkeypatch):
    """Ruleset 2, end to end -- through the database and the service, not the rules alone.

    This is the assertion the whole change exists for: before it, a colony on forest soil and
    a colony on bare desert produced identical alloy, and choosing a site was a formality with
    a scenery.
    """
    with transaction() as conn:
        generate_and_store(conn, "Approdo", 12)

    def a_tile(biome):
        with transaction() as conn:
            row = conn.execute(
                """SELECT id FROM world_tiles WHERE map_id = 1 AND biome = %s
                     AND elevation >= 0 AND temperature > -8 ORDER BY id LIMIT 1""",
                (biome,),
            ).fetchone()
        return row["id"] if row else None

    rich_tile, poor_tile = a_tile("temperate_forest"), a_tile("desert")
    if rich_tile is None or poor_tile is None:
        pytest.skip("this test world has neither a forest nor a desert")

    rich, poor = player("Fertile"), player("Arida")
    names = {rich["city_id"]: "Fertile", poor["city_id"]: "Arida"}
    with transaction() as conn:
        land(conn, rich["city_id"], rich["player_id"], rich_tile)
        land(conn, poor["city_id"], poor["player_id"], poor_tile)

    rewind(3600)
    now = freeze_clock(monkeypatch)
    earned = {}
    for who in (rich, poor):
        with transaction() as conn:
            row = conn.execute("SELECT * FROM cities WHERE id = %s",
                               (who["city_id"],)).fetchone()
            before = int(row["balance_milli"])
            service.advance(conn, row, now)
            after = conn.execute("SELECT balance_milli, site_food FROM cities WHERE id = %s",
                                 (who["city_id"],)).fetchone()
        earned[names[who["city_id"]]] = (int(after["balance_milli"]) - before,
                                         after["site_food"])

    (rich_alloy, rich_food), (poor_alloy, poor_food) = earned["Fertile"], earned["Arida"]
    assert rich_food > poor_food, earned
    assert rich_alloy > poor_alloy, earned
