from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient

from app import service
from app.db import database_now, transaction
from app.main import app
from app.service import (
    DomainError, balance, build_extractor, enter_world, found_colony, register,
)


PASSWORD = "correct-horse-battery"


def account(handle):
    with transaction() as conn:
        result = register(conn, handle, PASSWORD)
        enter_world(conn, result["player_id"])
        return result


def test_upgrade_from_foundation_backfills_order_fingerprint(database_at_0001):
    player_id, city_id, key = uuid4(), uuid4(), uuid4()
    with transaction() as conn:
        now = database_now(conn)
        conn.execute("INSERT INTO players VALUES (%s, %s, %s)", (player_id, "a" * 64, now))
        conn.execute(
            "INSERT INTO cities(id, owner_id, name, created_at, settled_at) VALUES (%s, %s, 'Legacy', %s, %s)",
            (city_id, player_id, now, now),
        )
        conn.execute(
            """INSERT INTO orders(city_id, idempotency_key, kind, choice, target_tick, submitted_at)
               VALUES (%s, %s, 'upgrade', NULL, 1, %s)""",
            (city_id, key, now),
        )
    command.upgrade(database_at_0001, "head")
    with transaction() as conn:
        record = conn.execute("SELECT * FROM idempotency_records WHERE idempotency_key=%s", (key,)).fetchone()
        assert record["action_kind"] == "strategic_order"
        assert len(record["payload_hash"]) == 64
        now = database_now(conn)
        conn.execute(
            "INSERT INTO cities(id, owner_id, name, created_at, settled_at) VALUES (%s, %s, 'Second', %s, %s)",
            (uuid4(), player_id, now, now),
        )
        assert conn.execute("SELECT count(*) AS n FROM cities WHERE owner_id=%s", (player_id,)).fetchone()["n"] == 2


def test_auth_uses_argon2_hashed_password_and_hashed_httponly_session(database):
    with TestClient(app) as client:
        response = client.post("/auth/register", json={"handle": "Pilot_One", "password": PASSWORD})
        assert response.status_code == 201
        assert response.json()["handle"] == "pilot_one"
        assert "token" not in response.json()
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        raw_token = client.cookies.get("exilium_session")
        assert raw_token
        assert client.get("/me").status_code == 200
    with transaction() as conn:
        player = conn.execute("SELECT token_hash, password_hash FROM players WHERE handle='pilot_one'").fetchone()
        session = conn.execute("SELECT token_hash FROM auth_sessions").fetchone()
        assert player["token_hash"] is None
        assert player["password_hash"].startswith("$argon2")
        assert PASSWORD not in player["password_hash"]
        assert session["token_hash"] == service.token_hash(raw_token)
        assert raw_token != session["token_hash"]


def test_production_forces_secure_cookie_and_validates_authenticated_origin(database, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("TRUSTED_ORIGINS", "https://game.example")
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/auth/register", json={"handle": "securepilot", "password": PASSWORD})
        assert "secure" in response.headers["set-cookie"].lower()
        assert client.get("/me").status_code == 200
        assert client.post("/worlds/exilium-prime/enter").status_code == 403
        assert client.post(
            "/worlds/exilium-prime/enter", headers={"Origin": "https://evil.example"}
        ).status_code == 403
        monkeypatch.delenv("TRUSTED_ORIGINS")
        assert client.post(
            "/worlds/exilium-prime/enter", headers={"Origin": "https://game.example"}
        ).status_code == 403
        monkeypatch.setenv("TRUSTED_ORIGINS", "https://game.example")
        assert client.post(
            "/worlds/exilium-prime/enter", headers={"Origin": "https://game.example"}
        ).status_code == 200
        assert client.post("/auth/logout", headers={"Origin": "https://game.example"}).status_code == 204
        assert client.get("/me").status_code == 401
    with transaction() as conn:
        assert conn.execute("SELECT revoked_at IS NOT NULL AS revoked FROM auth_sessions").fetchone()["revoked"]


def test_login_is_generic_and_expired_session_is_rejected(database):
    with TestClient(app) as client:
        client.post("/auth/register", json={"handle": "returning", "password": PASSWORD})
        assert client.post("/auth/login", json={"handle": "returning", "password": "wrong-password"}).status_code == 401
        assert client.post("/auth/login", json={"handle": "missing", "password": "wrong-password"}).json()["detail"] == "Invalid handle or password"
        with transaction() as conn:
            conn.execute(
                """UPDATE auth_sessions
                   SET created_at = clock_timestamp() - interval '2 days',
                       expires_at = clock_timestamp() - interval '1 day'"""
            )
        assert client.get("/me").status_code == 401


def test_enter_world_is_idempotent_and_required_for_cells(database):
    with TestClient(app) as client:
        client.post("/auth/register", json={"handle": "entrant", "password": PASSWORD})
        assert client.get("/worlds/exilium-prime/cells").status_code == 403
        first = client.post("/worlds/exilium-prime/enter")
        second = client.post("/worlds/exilium-prime/enter")
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert len(client.get("/worlds/exilium-prime/cells").json()) == 7
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM world_memberships").fetchone()["n"] == 1


def test_full_loop_survives_relogin_and_accrues_offline(database, monkeypatch):
    with transaction() as conn:
        clock = [database_now(conn)]
    monkeypatch.setattr(service, "database_now", lambda _conn: clock[0])
    with TestClient(app) as first_client:
        first_client.post("/auth/register", json={"handle": "founder", "password": PASSWORD})
        first_client.post("/worlds/exilium-prime/enter")
        key = str(uuid4())
        colony = first_client.post(
            "/worlds/exilium-prime/colonies",
            headers={"Idempotency-Key": key}, json={"name": "Dawn", "cell_id": 1},
        )
        assert colony.status_code == 201
        assert first_client.post(
            "/worlds/exilium-prime/colonies",
            headers={"Idempotency-Key": key}, json={"name": "Dawn", "cell_id": 1},
        ).json() == colony.json()
        mismatch = first_client.post(
            "/worlds/exilium-prime/colonies",
            headers={"Idempotency-Key": key}, json={"name": "Other", "cell_id": 1},
        )
        assert mismatch.status_code == 409
        assert first_client.post(
            "/worlds/exilium-prime/colonies",
            headers={"Idempotency-Key": str(uuid4())}, json={"name": "Second", "cell_id": 2},
        ).status_code == 409
        city_id = colony.json()["id"]
        build_key = str(uuid4())
        built = first_client.post(
            f"/cities/{city_id}/buildings/extractor",
            headers={"Idempotency-Key": build_key}, json={},
        )
        assert built.status_code == 201
        assert first_client.post(
            f"/cities/{city_id}/buildings/extractor",
            headers={"Idempotency-Key": build_key}, json={},
        ).json() == built.json()
    clock[0] += timedelta(seconds=10)
    with TestClient(app) as reopened:
        assert reopened.post("/auth/login", json={"handle": "founder", "password": PASSWORD}).status_code == 200
        state = reopened.get(f"/cities/{city_id}").json()
        assert state["extractors"] == 1
        assert state["production_milli_per_second"] == "35"
        assert state["alloy_milli"] == "40350"
        assert reopened.get(f"/cities/{city_id}").json()["alloy_milli"] == "40350"
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM cities").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM city_buildings").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM resource_ledger WHERE reason='genesis'").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM resource_ledger WHERE reason='extractor'").fetchone()["n"] == 1
        hashes = conn.execute("SELECT payload_hash FROM idempotency_records ORDER BY id").fetchall()
        assert hashes and all(len(row["payload_hash"]) == 64 for row in hashes)


def test_invalid_and_occupied_cells_are_rejected_under_contention(database):
    first, second = account("alpha"), account("bravo")
    with pytest.raises(DomainError) as invalid, transaction() as conn:
        found_colony(conn, first["player_id"], uuid4(), "Bad", 3)
    assert invalid.value.status == 422

    def compete(player, name):
        try:
            with transaction() as conn:
                return found_colony(conn, player["player_id"], uuid4(), name, 1)
        except DomainError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: compete(*args), [(first, "A"), (second, "B")]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results


def test_foundation_rolls_back_city_ledger_and_idempotency_together(database, monkeypatch):
    player = account("rollback")
    original = service.entry

    def fail_after_credit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after genesis")

    monkeypatch.setattr(service, "entry", fail_after_credit)
    with pytest.raises(RuntimeError), transaction() as conn:
        found_colony(conn, player["player_id"], uuid4(), "Rollback", 1)
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM cities").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM resource_ledger").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM idempotency_records").fetchone()["n"] == 0


def test_schema_allows_future_non_capital_colonies_for_same_owner(database):
    player = account("multicity")
    with transaction() as conn:
        first = found_colony(conn, player["player_id"], uuid4(), "Capital", 1)
        now = database_now(conn)
        conn.execute(
            """INSERT INTO cities(id, owner_id, name, created_at, settled_at, cell_id, is_capital)
               VALUES (%s, %s, 'Future colony', %s, %s, 2, false)""",
            (uuid4(), player["player_id"], now, now),
        )
        assert first["is_capital"]
        assert conn.execute("SELECT count(*) AS n FROM cities WHERE owner_id=%s", (player["player_id"],)).fetchone()["n"] == 2


def test_extractor_concurrent_retry_debits_once_and_rejects_cross_payload(database):
    player = account("builder")
    with transaction() as conn:
        colony = found_colony(conn, player["player_id"], uuid4(), "Forge", 1)
    city_id, key = colony["id"], uuid4()

    def build(_):
        with transaction() as conn:
            return build_extractor(conn, city_id, player["player_id"], key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(build, range(4)))
    assert len({result["id"] for result in results}) == 1
    with transaction() as conn:
        production = conn.execute(
            "SELECT COALESCE(sum(amount), 0) AS total FROM resource_ledger WHERE city_id=%s AND reason='production'",
            (city_id,),
        ).fetchone()["total"]
        assert balance(conn, city_id) == 40000 + production
        assert conn.execute("SELECT count(*) AS n FROM resource_ledger WHERE reason='extractor'").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM city_buildings").fetchone()["n"] == 1
        with pytest.raises(DomainError) as mismatch:
            service.submit_order(conn, city_id, player["player_id"], key, "upgrade", None)
        assert mismatch.value.status == 409


def test_extractor_insufficient_balance_has_no_partial_effect(database):
    player = account("poorbuilder")
    with transaction() as conn:
        colony = found_colony(conn, player["player_id"], uuid4(), "Lean", 1)
        service.entry(conn, colony["id"], -50000, "upgrade", "fixture:spend", database_now(conn))
    with pytest.raises(DomainError) as error, transaction() as conn:
        build_extractor(conn, colony["id"], player["player_id"], uuid4())
    assert error.value.status == 409
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM city_buildings").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM idempotency_records WHERE action_kind='build_extractor'").fetchone()["n"] == 0


def test_extractor_authorization_and_failure_are_atomic(database, monkeypatch):
    owner, intruder = account("owner"), account("intruder")
    with transaction() as conn:
        colony = found_colony(conn, owner["player_id"], uuid4(), "Guarded", 1)
    with pytest.raises(DomainError) as forbidden, transaction() as conn:
        build_extractor(conn, colony["id"], intruder["player_id"], uuid4())
    assert forbidden.value.status == 404
    with transaction() as conn:
        before = balance(conn, colony["id"])

    original = service.entry

    def fail_after_debit(*args, **kwargs):
        original(*args, **kwargs)
        if args[3] == "extractor":
            raise RuntimeError("injected after extractor debit")

    monkeypatch.setattr(service, "entry", fail_after_debit)
    with pytest.raises(RuntimeError), transaction() as conn:
        build_extractor(conn, colony["id"], owner["player_id"], uuid4())
    with transaction() as conn:
        assert balance(conn, colony["id"]) == before
        assert conn.execute("SELECT count(*) AS n FROM city_buildings").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM resource_ledger WHERE reason='extractor'").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM idempotency_records WHERE action_kind='build_extractor'").fetchone()["n"] == 0
