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
    DomainError, balance, cast_vote, current_policy, land, provision, read_city,
    start_upgrade, stock,
)
from app.sim.config import (
    RESOURCES, RULESET, STARTING_STOCK, WORK_KINDS, harvest_rate, store_cap,
    upgrade_cost, upgrade_duration,
)
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
        # Paid, but not yet arrived. Paid in MATERIALS: what a level costs is stone and
        # timber, and both leave the stores the moment the work starts.
        held = stock(conn, p["city_id"])
        for resource, amount in upgrade_cost(0).items():
            assert held[resource] == STARTING_STOCK[resource] - amount
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
        held = stock(conn, p["city_id"])
        for resource, amount in upgrade_cost(0).items():
            assert held[resource] == STARTING_STOCK[resource] - amount
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
    earned = int(view["stock_milli"]["stone"]) - STARTING_STOCK["stone"]
    # Sessanta secondi al tasso bilanciato sono il minimo, sessanta a quello industriale il
    # massimo: la verita' sta in mezzo, perche' il cambio e' avvenuto a meta'. Fuori da quella
    # fascia significa che la linea temporale e' stata ignorata in una delle due direzioni.
    slow = 60 * harvest_rate("stone", 0, 0, "balanced")
    fast = 60 * harvest_rate("stone", 0, 0, "industrial")
    assert slow <= earned < fast, (earned, slow, fast)


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
    # Il fermo dell'orologio va PRIMA dei giocatori, come in ogni altra prova qui.
    #
    # Messo dopo, questa prova dipendeva dal caso: `database_now` tronca al secondo, e il
    # primo periodo di politica nasce insieme ai giocatori. Se la loro creazione scavalcava
    # un secondo intero -- cosa che succede quando la macchina e' carica -- il periodo
    # iniziale aveva lunghezza positiva, non si accorpava, e l'asserzione trovava due righe
    # invece di una. Non un difetto del gioco: un difetto della prova, che falliva una volta
    # ogni tanto e si sarebbe presa la colpa di qualcos'altro.
    now = freeze_clock(monkeypatch)
    first, second = player("A"), player("B")
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
        # Svuota la pietra: il legname resta, quindi un avanzamento a meta' sarebbe possibile
        # solo se qualcuno spendesse cio' che c'e' prima di accorgersi che manca il resto.
        service.entry(conn, p["city_id"], -STARTING_STOCK["stone"], "upgrade",
                      "fixture-spend", database_now(conn), "stone")
    with pytest.raises(DomainError) as error, transaction() as conn:
        start_upgrade(conn, p["city_id"], p["player_id"], uuid4())
    assert error.value.detail == "insufficient_stone"
    with transaction() as conn:
        held = stock(conn, p["city_id"])
        assert held["stone"] == 0
        # E il legname NON e' stato toccato: un rifiuto non lascia meta' conto pagato.
        assert held["timber"] == STARTING_STOCK["timber"]
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
        # Il magazzino che l'API mostra e' esattamente la somma del ledger, risorsa per
        # risorsa: e' l'invariante di sempre, vista da fuori invece che dal database.
        from collections import Counter
        summed = Counter()
        for row in ledger:
            summed[row["resource"]] += int(row["amount"])
        for resource, total in summed.items():
            assert int(state["stock_milli"][resource]) == total, resource
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
    # Tutti e quattro vedono lo stesso magazzino...
    assert len({tuple(sorted(view["stock_milli"].items())) for view in views}) == 1
    with transaction() as conn:
        # ... e la produzione e' stata scritta UNA volta per risorsa, non quattro.
        by_resource = conn.execute(
            "SELECT resource, count(*) AS n FROM resource_ledger"
            " WHERE reason='production' GROUP BY resource"
        ).fetchall()
        # Una riga per risorsa che si e' MOSSA, e nessuna scritta due volte. La lega non
        # compare: senza una fonderia nessuno la produce, ed e' esattamente il punto.
        written = {row["resource"]: int(row["n"]) for row in by_resource}
        assert set(written) <= set(RESOURCES) and written
        assert set(written.values()) == {1}


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
            # Una riga per risorsa che si e' mossa, non sei letture che scrivono sei volte.
            # Senza opere la lega non si muove, quindi il conto e' minore dell'elenco.
            assert 0 < n <= len(RESOURCES)
            held = stock(conn, p["city_id"])
            assert held["stone"] == STARTING_STOCK["stone"] + 60 * harvest_rate("stone", 0, 0)


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
        # L'invariante che regge tutto, ora per RISORSA: ogni cursore materializzato e'
        # esattamente la somma del ledger di quella risorsa. Il ledger resta l'unica fonte
        # di verita' e resta immutabile; le scorte sono un cursore ricostruibile.
        rows = conn.execute(
            """SELECT s.city_id, s.resource, s.amount_milli,
                      (SELECT COALESCE(SUM(amount), 0) FROM resource_ledger l
                        WHERE l.city_id = s.city_id AND l.resource = s.resource) AS ledger_sum
                 FROM city_stock s ORDER BY s.city_id, s.resource"""
        ).fetchall()
        assert rows, "nessuna scorta da verificare"
        for row in rows:
            assert int(row["amount_milli"]) == int(row["ledger_sum"]), dict(row)
        # ... e non e' vera per vuoto: qualcosa e' stato prodotto e qualcosa speso.
        assert any(int(row["amount_milli"]) > 0 for row in rows)
def test_ledger_enforces_no_overdraft_and_duplicate_event(database):
    p = player()
    # Lo scoperto e' rifiutato PER RISORSA: avere legname non autorizza a spendere pietra.
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        service.entry(conn, p["city_id"], -STARTING_STOCK["stone"] - 1, "upgrade",
                      "bad-debit", database_now(conn), "stone")
    with pytest.raises(psycopg.errors.UniqueViolation), transaction() as conn:
        service.entry(conn, p["city_id"], 1, "genesis", f"genesis:{p['city_id']}:stone",
                      database_now(conn), "stone")


def test_materialized_balance_rejects_overdraft_without_scanning_ledger(database):
    p = player()
    with transaction() as conn:
        service.entry(conn, p["city_id"], -STARTING_STOCK["timber"], "upgrade",
                      "spend-all", database_now(conn), "timber")
        assert stock(conn, p["city_id"])["timber"] == 0
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        service.entry(conn, p["city_id"], -1, "upgrade", "overdraft", database_now(conn), "timber")
    with transaction() as conn:
        assert int(conn.execute(
            "SELECT amount_milli FROM city_stock WHERE city_id = %s AND resource = 'timber'",
            (p["city_id"],),
        ).fetchone()["amount_milli"]) == 0


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
            before = stock(conn, who["city_id"])["food"]
            service.advance(conn, row, now)
            after = stock(conn, who["city_id"])["food"]
        earned[names[who["city_id"]]] = (after - before, row["site_food"])

    (rich_grown, rich_food), (poor_grown, poor_food) = earned["Fertile"], earned["Arida"]
    assert rich_food > poor_food, earned
    # La terra grassa NUTRE di piu': e' il cibo a portare il tetto della colonia, quindi e'
    # qui che la scelta del sito si sente prima che altrove.
    assert rich_grown > poor_grown, earned


def test_a_colony_says_when_it_will_stop_earning(database, monkeypatch):
    """La meta' che rende vivibile lo stallo alla Anno in un mondo che cammina mentre dormi.

    Fermarsi e' la tensione voluta; fermarsi a sorpresa e' una punizione per chi ha un lavoro.
    Quindi il momento va detto PRIMA, e va detto dall'API -- non solo calcolabile in teoria.
    """
    p = player()
    freeze_clock(monkeypatch)
    with transaction() as conn:
        view = read_city(conn, p["city_id"], p["player_id"])

    forecast = view["stalls_in_seconds"]
    assert set(forecast) == set(RESOURCES)
    assert all(seconds is None or seconds > 0 for seconds in forecast.values())

    # E la previsione e' quella vera: portando avanti l'orologio di quel tanto, il magazzino
    # e' pieno e la colonia ha davvero smesso di guadagnare.
    when = forecast["stone"]
    assert when is not None
    with transaction() as conn:
        clock = db.database_now(conn)
    monkeypatch.setattr(db, "database_now", lambda conn: clock + timedelta(seconds=when + 60))
    with transaction() as conn:
        later = read_city(conn, p["city_id"], p["player_id"])
    assert int(later["stock_milli"]["stone"]) == store_cap(later["level"])
    # Zero, non None: "gia' fermo" e "non si fermera' mai" sono due stati diversi, e
    # confonderli farebbe leggere un magazzino pieno come una risorsa che non arriva.
    assert later["stalls_in_seconds"]["stone"] == 0


def test_the_browser_is_told_which_pages_may_spend_a_token(database, monkeypatch):
    """Il visore e' un sito statico su un altro host, quindi la schermata della citta' e'
    cross-origin per progetto. Il permesso va dato per NOME, mai a chiunque.

    Con un token in un header `Authorization` -- e non in un cookie -- un permesso aperto non
    verrebbe rifiutato dal browser: lascerebbe semplicemente che qualsiasi pagina di internet
    spenda un token di cui sia venuta in possesso. E' un difetto peggiore proprio perche'
    silenzioso.
    """
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://visore.test")
    import importlib

    from app import main as main_module
    reloaded = importlib.reload(main_module)
    assert reloaded.ALLOWED_ORIGINS == ["https://visore.test"]
    assert "*" not in reloaded.ALLOWED_ORIGINS

    with TestClient(reloaded.app) as client:
        allowed = client.options(
            "/me/cities",
            headers={"Origin": "https://visore.test",
                     "Access-Control-Request-Method": "GET"},
        )
        assert allowed.headers.get("access-control-allow-origin") == "https://visore.test"

        # Una pagina qualunque non riceve il permesso.
        stranger = client.options(
            "/me/cities",
            headers={"Origin": "https://altrove.test",
                     "Access-Control-Request-Method": "GET"},
        )
        assert stranger.headers.get("access-control-allow-origin") is None

    monkeypatch.delenv("ALLOWED_ORIGINS")
    importlib.reload(main_module)


def test_every_resource_the_rules_can_produce_is_a_resource_the_ledger_accepts(database):
    """Un difetto trovato costruendo, e che nessun test prendeva: il minerale e' stato
    aggiunto alle regole e alla riga della citta', ma l'elenco delle risorse ammesse nel
    ledger e' rimasto quello di prima. Si poteva produrre e non si poteva scrivere -- e non si
    vede finche' qualcuno non estrae il primo grammo.

    Questo confronta i due elenchi invece di fidarsi che restino allineati.
    """
    p = player()
    with transaction() as conn:
        now = database_now(conn)
        for resource in RESOURCES:
            # Se il CHECK non conosce la risorsa, questo alza CheckViolation e il test cade.
            service.entry(conn, p["city_id"], 1, "genesis",
                          f"allineamento:{resource}", now, resource)
        held = stock(conn, p["city_id"])
    for resource in RESOURCES:
        assert held[resource] >= 1, resource


def test_the_api_accepts_every_plant_the_rules_know(database):
    """Lo stesso difetto del minerale nel ledger, in un altro punto: un impianto aggiunto alle
    regole e al database, e rifiutato dall'API perche' lassu' l'elenco era un altro. Scoperto
    costruendo -- il solare tornava "Input should be 'smelter'".

    Questo confronta i due elenchi invece di sperare che restino allineati.
    """
    p = player()
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {p['token']}"}
        for kind in WORK_KINDS:
            answer = client.post(
                f"/cities/{p['city_id']}/works",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"kind": kind},
            )
            # Puo' rifiutare per mancanza di materiale o perche' la colonia e' occupata --
            # quelle sono risposte del gioco. Non deve rifiutare perche' NON SA cosa sia.
            assert answer.status_code != 422, (kind, answer.json())
            if answer.status_code == 409:
                assert answer.json()["detail"] != "unknown_work", kind

    # E un impianto che non esiste resta rifiutato, o il test sopra passerebbe per vuoto.
    with TestClient(app) as client:
        answer = client.post(
            f"/cities/{p['city_id']}/works",
            headers={"Authorization": f"Bearer {p['token']}", "Idempotency-Key": str(uuid4())},
            json={"kind": "reattore-a-fusione"},
        )
    assert answer.status_code == 422


def landed_player(name="Colono"):
    """Un giocatore la cui colonia e' DAVVERO a terra: senza atterrare, le attitudini del
    sito sono nulle e una centrale solare non produce niente -- che e' corretto, e rende il
    fixture in orbita inadatto a provare l'energia."""
    with transaction() as conn:
        if not conn.execute("SELECT 1 FROM world_map WHERE id = 1").fetchone():
            generate_and_store(conn, "Approdo", 12)
    who = player(name)
    with transaction() as conn:
        tile = conn.execute(
            """SELECT id FROM world_tiles WHERE map_id = 1 AND elevation >= 0
                 AND biome NOT IN ('ocean', 'lake', 'sea_ice') AND temperature > -8
                 AND id NOT IN (SELECT tile_id FROM cities WHERE tile_id IS NOT NULL)
               ORDER BY rainfall LIMIT 1"""
        ).fetchone()
        land(conn, who["city_id"], who["player_id"], tile["id"])
    return who


def test_a_plant_can_be_paused_resumed_and_pulled_down(database, monkeypatch):
    """La cosa che mancava, e che rendeva una fonderia una condanna: senza un modo di dire
    "non adesso", un solo impianto poteva mangiare il legname per sempre -- e il legname serve
    anche a costruire.

    Accendere e spegnere NON occupano la colonia: sono un interruttore, non un lavoro, e
    chiedere un impegno di tre ore per cambiare idea sarebbe stato punire il ripensamento.
    """
    p = landed_player("Assolata")
    freeze_clock(monkeypatch)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO city_works (city_id, kind, count) VALUES (%s, 'solar', 2)",
            (p["city_id"],),
        )

    with transaction() as conn:
        view = service.set_work_running(conn, p["city_id"], p["player_id"], "solar", 1)
    assert view["works"]["solar"] == 2 and view["works_idle"]["solar"] == 1
    # Una spenta non produce: la corrente e' un flusso, e cio' che e' fermo non ne fa.
    with transaction() as conn:
        both = service.set_work_running(conn, p["city_id"], p["player_id"], "solar", 2)
    assert both["power_made"] > view["power_made"]

    # Non si possono accendere impianti che non si hanno.
    with pytest.raises(DomainError) as error, transaction() as conn:
        service.set_work_running(conn, p["city_id"], p["player_id"], "solar", 9)
    assert error.value.detail == "out_of_range"

    # Abbattere toglie uno e non chiede permesso al tempo: e' istantaneo.
    with transaction() as conn:
        after = service.demolish_work(conn, p["city_id"], p["player_id"], "solar")
    assert after["works"]["solar"] == 1
    with transaction() as conn:
        service.demolish_work(conn, p["city_id"], p["player_id"], "solar")
    with pytest.raises(DomainError) as error, transaction() as conn:
        service.demolish_work(conn, p["city_id"], p["player_id"], "solar")
    assert error.value.detail == "no_such_work"


def test_pausing_settles_first_so_the_last_hour_is_not_rewritten(database, monkeypatch):
    """Spegnere un impianto non deve riscrivere cio' che la colonia ha gia' prodotto: quelle
    ore le ha prodotte col vecchio assetto, e il cursore va portato al presente PRIMA che
    l'assetto cambi."""
    p = landed_player("Paziente")
    with transaction() as conn:
        conn.execute(
            "INSERT INTO city_works (city_id, kind, count) VALUES (%s, 'solar', 1)",
            (p["city_id"],),
        )
    rewind(600)
    freeze_clock(monkeypatch)

    with transaction() as conn:
        before = stock(conn, p["city_id"])["stone"]
        service.set_work_running(conn, p["city_id"], p["player_id"], "solar", 0)
        after = stock(conn, p["city_id"])["stone"]
    # I dieci minuti di raccolto sono stati incassati, non persi nel cambio di assetto.
    assert after > before
