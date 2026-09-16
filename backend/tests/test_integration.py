from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from fastapi.testclient import TestClient

from app import service
from app.db import database_now, transaction
from app.main import app
from app.service import (
    DomainError, balance, create_session, entry, lock_world, read_city, require_current,
    run_tick, submit_order,
)
from app.worker import catch_up


def player(name="Exilium"):
    with transaction() as conn:
        world = lock_world(conn)
        now = database_now(conn)
        require_current(world, now)
        owner, city = uuid4(), uuid4()
        conn.execute("INSERT INTO players(id, token_hash, created_at) VALUES (%s, NULL, %s)", (owner, now))
        conn.execute(
            "INSERT INTO cities(id, owner_id, name, created_at, settled_at) VALUES (%s, %s, %s, %s, %s)",
            (city, owner, name, now, now),
        )
        entry(conn, city, 100000, "genesis", f"genesis:{city}", now)
        return {"player_id": owner, "city_id": city}


def age_world(days=1):
    """Test-only SQL fixture. No client or production clock override exists."""
    with transaction() as conn:
        due = database_now(conn).replace(hour=0, minute=0, second=0) - timedelta(days=days - 1)
        start = due - timedelta(seconds=10)
        conn.execute("UPDATE world SET next_tick_at = %s", (due,))
        conn.execute("UPDATE cities SET created_at = %s, settled_at = %s", (start, start))
    return due


def enqueue(p, kind="upgrade", choice=None, key=None):
    with transaction() as conn:
        return submit_order(conn, p["city_id"], p["player_id"], key or uuid4(), kind, choice)


def test_migration_rerun_and_world_singleton(database):
    command.upgrade(database, "head")
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM world").fetchone()["n"] == 1
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute("INSERT INTO world SELECT 2, policy, last_tick, next_tick_at FROM world")


def test_tick_exact_boundary_policy_upgrade_and_retry(database):
    p = player()
    key = uuid4()
    order = enqueue(p, key=key)
    enqueue(p, "policy_vote", "industrial")
    with transaction() as conn:
        before = balance(conn, p["city_id"])
    due = age_world()
    with transaction() as conn:
        result = run_tick(conn)
        assert result["number"] == 1
        expected = before + 100 - 100000
        assert balance(conn, p["city_id"]) == expected  # 10 seconds at old rate; upgrade cost.
        assert conn.execute("SELECT settled_at FROM cities").fetchone()["settled_at"] == due
        assert conn.execute("SELECT level FROM cities").fetchone()["level"] == 1
    with transaction() as conn:
        assert run_tick(conn) is None
        city = conn.execute("SELECT * FROM cities").fetchone()
        service.settle(conn, city, due + timedelta(seconds=10), "industrial")
        assert balance(conn, p["city_id"]) == expected + 250  # New policy and level only AFTER boundary.
    assert enqueue(p, key=key)["id"] == order["id"]
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM ticks").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM resource_ledger WHERE reason='upgrade'").fetchone()["n"] == 1


def test_tick_crash_rolls_back_all_effects(database, monkeypatch):
    p = player()
    enqueue(p)
    with transaction() as conn:
        before = balance(conn, p["city_id"])
    age_world()
    original = service.entry

    def crash_after_debit(conn, city, amount, reason, key, at):
        original(conn, city, amount, reason, key, at)
        if reason == "upgrade":
            raise RuntimeError("injected failure after debit")

    monkeypatch.setattr(service, "entry", crash_after_debit)
    with pytest.raises(RuntimeError), transaction() as conn:
        run_tick(conn)
    with transaction() as conn:
        assert balance(conn, p["city_id"]) == before
        assert conn.execute("SELECT level FROM cities").fetchone()["level"] == 0
        assert conn.execute("SELECT status FROM orders").fetchone()["status"] == "pending"
        assert conn.execute("SELECT last_tick FROM world").fetchone()["last_tick"] == 0
        assert conn.execute("SELECT count(*) AS n FROM ticks").fetchone()["n"] == 0
    monkeypatch.setattr(service, "entry", original)
    assert catch_up() == 1


def test_competing_workers_commit_once(database):
    p = player()
    enqueue(p)
    with transaction() as conn:
        before = balance(conn, p["city_id"])
    age_world()
    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(lambda _: catch_up(), range(4)))
    assert sum(counts) == 1
    with transaction() as conn:
        assert balance(conn, p["city_id"]) == before + 100 - 100000


def test_concurrent_order_retries_and_conflicts(database):
    p, key = player(), uuid4()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: enqueue(p, key=key), range(4)))
    assert len({r["id"] for r in results}) == 1
    with pytest.raises(DomainError) as error:
        enqueue(p, "policy_vote", "balanced", key)
    assert error.value.status == 409
    with pytest.raises(DomainError) as error:
        enqueue(p)
    assert error.value.status == 409


def test_catchup_preserves_every_day_and_policy_period(database):
    p = player()
    enqueue(p, "policy_vote", "industrial")
    age_world(days=3)
    assert catch_up(limit=2) == 2
    assert catch_up() == 1
    with transaction() as conn:
        assert balance(conn, p["city_id"]) == 100000 + 100 + 2 * 86400 * 20
        assert [r["number"] for r in conn.execute("SELECT number FROM ticks ORDER BY number").fetchall()] == [1, 2, 3]


def test_pending_tick_blocks_new_economy_but_allows_retry(database):
    p, key = player(), uuid4()
    order = enqueue(p, key=key)
    age_world()
    assert enqueue(p, key=key)["id"] == order["id"]
    with pytest.raises(DomainError) as error, transaction() as conn:
        read_city(conn, p["city_id"], p["player_id"])
    assert error.value.status == 503
    with pytest.raises(DomainError) as error:
        enqueue(p, "policy_vote", "balanced")
    assert error.value.status == 503


@pytest.mark.parametrize("statement", [
    "UPDATE resource_ledger SET amount=1",
    "DELETE FROM resource_ledger",
    "TRUNCATE resource_ledger",
    "UPDATE ticks SET ruleset=1",
    "DELETE FROM ticks",
    "TRUNCATE ticks",
])
def test_audit_tables_are_immutable(database, statement):
    player()
    age_world()
    catch_up()
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute(statement)


def test_ledger_enforces_no_overdraft_and_duplicate_event(database):
    p = player()
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        service.entry(conn, p["city_id"], -100001, "upgrade", "bad-debit", database_now(conn))
    with pytest.raises(psycopg.errors.UniqueViolation), transaction() as conn:
        service.entry(conn, p["city_id"], 1, "genesis", f"genesis:{p['city_id']}", database_now(conn))


def test_insufficient_upgrade_has_no_partial_effects(database):
    p = player()
    enqueue(p)
    with transaction() as conn:
        service.entry(conn, p["city_id"], -100000, "upgrade", "fixture-spend", database_now(conn))
        before = balance(conn, p["city_id"])
    age_world()
    catch_up()
    with transaction() as conn:
        assert balance(conn, p["city_id"]) == before + 100
        assert conn.execute("SELECT level FROM cities").fetchone()["level"] == 0
        assert conn.execute("SELECT outcome FROM orders").fetchone()["outcome"] == "insufficient_alloy"


def test_api_authorization_validation_idempotency_and_ledger(database):
    p, other = player(), player("Other")
    with transaction() as conn:
        session = create_session(conn, p["player_id"])
    headers = {"Idempotency-Key": str(uuid4())}
    path = f"/cities/{p['city_id']}"
    with TestClient(app) as client:
        client.cookies.set("exilium_session", session)
        assert client.get("/health/ready").status_code == 200
        assert client.get(f"/cities/{other['city_id']}", headers=headers).status_code == 404
        assert client.post(f"/cities/{other['city_id']}/orders", headers=headers, json={"kind": "upgrade"}).status_code == 404
        assert client.post(path + "/orders", headers=headers, json={"kind": "upgrade", "amount": 9999}).status_code == 422
        assert client.post(path + "/orders", headers=headers, json={"kind": "policy_vote"}).status_code == 422
        assert client.post(path + "/orders", json={"kind": "upgrade"}).status_code == 422
        first = client.post(path + "/orders", headers=headers, json={"kind": "upgrade"})
        second = client.post(path + "/orders", headers=headers, json={"kind": "upgrade"})
        assert first.status_code == 200 and second.json() == first.json()
        assert client.post(path + "/orders", headers=headers, json={"kind": "policy_vote", "choice": "industrial"}).status_code == 409
        state = client.get(path, headers=headers).json()
        ledger = client.get(path + "/ledger", headers=headers).json()
        assert int(state["alloy_milli"]) == sum(int(row["amount"]) for row in ledger)
        assert client.get(path + "/ledger?limit=201", headers=headers).status_code == 422
        assert client.get(path + "/orders", headers=headers).json()[0]["id"] == first.json()["id"]
        age_world()
        response = client.get(path, headers=headers)
        assert response.status_code == 503 and response.headers["Retry-After"] == "5"
        assert client.get("/health/ready").status_code == 503


def test_simultaneous_settlements_never_duplicate_production(database, monkeypatch):
    p = player()
    with transaction() as conn:
        now = database_now(conn)
        conn.execute("UPDATE cities SET created_at=%s, settled_at=%s", (now - timedelta(seconds=37), now - timedelta(seconds=37)))
    monkeypatch.setattr(service, "database_now", lambda conn: now)

    def read(_):
        with transaction() as conn:
            return read_city(conn, p["city_id"], p["player_id"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        snapshots = list(pool.map(read, range(4)))
    assert {snapshot["alloy_milli"] for snapshot in snapshots} == {"100370"}
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM resource_ledger WHERE reason='production'").fetchone()["n"] == 1


def test_exact_cutoff_rejects_order_and_runs_tick(database, monkeypatch):
    p = player()
    due = age_world()
    monkeypatch.setattr(service, "database_now", lambda conn: due)
    with pytest.raises(DomainError) as error:
        enqueue(p)
    assert error.value.status == 503
    with transaction() as conn:
        assert run_tick(conn)["number"] == 1
    accepted = enqueue(p)
    assert accepted["target_tick"] == 2
    assert accepted["submitted_at"] == due


def test_multiple_players_share_one_election(database):
    first, second, third = player("A"), player("B"), player("C")
    enqueue(first, "policy_vote", "industrial")
    enqueue(second, "policy_vote", "industrial")
    enqueue(third, "policy_vote", "balanced")
    age_world()
    catch_up()
    with transaction() as conn:
        assert conn.execute("SELECT policy FROM world").fetchone()["policy"] == "industrial"
        assert conn.execute("SELECT summary FROM ticks").fetchone()["summary"]["votes"] == {"industrial": 2, "balanced": 1}
