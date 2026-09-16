import hashlib
import json
import secrets
from datetime import timedelta
from uuid import uuid4

from psycopg.types.json import Jsonb
from pwdlib import PasswordHash

from app.db import database_now
from app.domain import (
    EXTRACTOR_COST, MAX_LEVEL, RULESET, STARTING_ALLOY, UPGRADE_COST,
    elected_policy, production_amount, production_rate,
)

password_hash = PasswordHash.recommended()
SESSION_TTL = timedelta(days=30)


class DomainError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def lock_world(conn):
    return conn.execute("SELECT * FROM world WHERE id = 1 FOR UPDATE").fetchone()


def require_current(world, now):
    if now >= world["next_tick_at"]:
        raise DomainError(503, "World tick pending; retry after recovery")


def owned_city(conn, city_id, owner_id):
    city = conn.execute(
        "SELECT * FROM cities WHERE id = %s AND owner_id = %s", (city_id, owner_id)
    ).fetchone()
    if city is None:
        raise DomainError(404, "City not found")
    return city


def balance(conn, city_id):
    return int(conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS balance FROM resource_ledger WHERE city_id = %s",
        (city_id,),
    ).fetchone()["balance"])


def entry(conn, city_id, amount, reason, event_key, effective_at):
    conn.execute(
        """INSERT INTO resource_ledger(city_id, amount, reason, event_key, effective_at)
           VALUES (%s, %s, %s, %s, %s)""",
        (city_id, amount, reason, event_key, effective_at),
    )


def extractor_count(conn, city_id):
    return int(conn.execute(
        "SELECT count(*) AS count FROM city_buildings WHERE city_id = %s AND kind = 'extractor'",
        (city_id,),
    ).fetchone()["count"])


def settle(conn, city, until, policy):
    count = extractor_count(conn, city["id"])
    amount = production_amount(city["settled_at"], until, policy, city["level"], count)
    if until == city["settled_at"]:
        return
    if amount:
        key = f"production:{city['id']}:{city['settled_at'].isoformat()}:{until.isoformat()}"
        entry(conn, city["id"], amount, "production", key, until)
    conn.execute("UPDATE cities SET settled_at = %s WHERE id = %s", (until, city["id"]))


def idempotency_replay(conn, player_id, key, action_kind, fingerprint):
    record = conn.execute(
        "SELECT * FROM idempotency_records WHERE player_id = %s AND idempotency_key = %s",
        (player_id, key),
    ).fetchone()
    if record is None:
        return None
    if record["action_kind"] != action_kind or record["payload_hash"] != fingerprint:
        raise DomainError(409, "Idempotency key was already used with a different payload")
    return record["result"]


def save_idempotency(conn, player_id, key, action_kind, fingerprint, result, now):
    return conn.execute(
        """INSERT INTO idempotency_records
               (player_id, idempotency_key, action_kind, payload_hash, result, created_at)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (player_id, key, action_kind, fingerprint, Jsonb(result), now),
    ).fetchone()["id"]


def create_session(conn, player_id):
    now = database_now(conn)
    raw = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO auth_sessions VALUES (%s, %s, %s, %s, %s, NULL)",
        (uuid4(), player_id, token_hash(raw), now, now + SESSION_TTL),
    )
    return raw


def register(conn, handle, password):
    normalized = handle.strip().lower()
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"register:{normalized}",))
    if conn.execute("SELECT 1 FROM players WHERE handle = %s", (normalized,)).fetchone():
        raise DomainError(409, "Handle is already registered")
    now, player_id = database_now(conn), uuid4()
    conn.execute(
        """INSERT INTO players(id, token_hash, created_at, handle, password_hash)
           VALUES (%s, NULL, %s, %s, %s)""",
        (player_id, now, normalized, password_hash.hash(password)),
    )
    return {"player_id": player_id, "handle": normalized, "token": create_session(conn, player_id)}


def login(conn, handle, password):
    player = conn.execute(
        "SELECT id, handle, password_hash FROM players WHERE handle = %s", (handle.strip().lower(),)
    ).fetchone()
    if player is None or not password_hash.verify(password, player["password_hash"]):
        raise DomainError(401, "Invalid handle or password")
    return {"player_id": player["id"], "handle": player["handle"], "token": create_session(conn, player["id"])}


def authenticate_session(conn, raw_token):
    if not raw_token:
        raise DomainError(401, "Authentication required")
    player = conn.execute(
        """SELECT p.id, p.handle FROM auth_sessions s
           JOIN players p ON p.id = s.player_id
           WHERE s.token_hash = %s AND s.revoked_at IS NULL
             AND s.expires_at > clock_timestamp()""",
        (token_hash(raw_token),),
    ).fetchone()
    if player is None:
        raise DomainError(401, "Invalid or expired session")
    return player


def revoke_session(conn, raw_token):
    if raw_token:
        conn.execute(
            """UPDATE auth_sessions SET revoked_at = date_trunc('second', clock_timestamp())
               WHERE token_hash = %s AND revoked_at IS NULL""",
            (token_hash(raw_token),),
        )


def profile(conn, player_id):
    player = conn.execute("SELECT id, handle FROM players WHERE id = %s", (player_id,)).fetchone()
    joined = conn.execute(
        "SELECT 1 FROM world_memberships WHERE world_id = 1 AND player_id = %s", (player_id,)
    ).fetchone() is not None
    cities = conn.execute(
        "SELECT id, name, is_capital FROM cities WHERE owner_id = %s ORDER BY created_at, id", (player_id,)
    ).fetchall()
    return {"id": player["id"], "handle": player["handle"], "entered_exilium_prime": joined, "cities": cities}


def enter_world(conn, player_id):
    world = lock_world(conn)
    now = database_now(conn)
    conn.execute(
        """INSERT INTO world_memberships(world_id, player_id, joined_at)
           VALUES (1, %s, %s) ON CONFLICT DO NOTHING""",
        (player_id, now),
    )
    return {"world_id": world["id"], "slug": world["slug"], "joined": True}


def available_cells(conn, player_id):
    if conn.execute(
        "SELECT 1 FROM world_memberships WHERE world_id = 1 AND player_id = %s", (player_id,)
    ).fetchone() is None:
        raise DomainError(403, "Enter exilium-prime before choosing a cell")
    return conn.execute(
        """SELECT c.id, c.q, c.r, c.terrain FROM world_cells c
           WHERE c.world_id = 1 AND c.buildable
             AND NOT EXISTS (SELECT 1 FROM cities city WHERE city.cell_id = c.id)
           ORDER BY c.id"""
    ).fetchall()


def found_colony(conn, player_id, key, name, cell_id):
    normalized_name = name.strip()
    fingerprint = payload_hash({"cell_id": cell_id, "name": normalized_name})
    world = lock_world(conn)
    replay = idempotency_replay(conn, player_id, key, "found_colony", fingerprint)
    if replay is not None:
        return replay
    now = database_now(conn)
    require_current(world, now)
    if conn.execute(
        "SELECT 1 FROM world_memberships WHERE world_id = 1 AND player_id = %s", (player_id,)
    ).fetchone() is None:
        raise DomainError(403, "Enter exilium-prime before founding a colony")
    # Slice rule only: the schema permits future non-capital colonies.
    if conn.execute("SELECT 1 FROM cities WHERE owner_id = %s", (player_id,)).fetchone():
        raise DomainError(409, "The first colony has already been founded")
    cell = conn.execute(
        "SELECT * FROM world_cells WHERE id = %s AND world_id = 1 FOR UPDATE", (cell_id,)
    ).fetchone()
    if cell is None or not cell["buildable"]:
        raise DomainError(422, "Cell is not valid for a colony")
    if conn.execute("SELECT 1 FROM cities WHERE cell_id = %s", (cell_id,)).fetchone():
        raise DomainError(409, "Cell is already occupied")
    city_id = uuid4()
    conn.execute(
        """INSERT INTO cities
               (id, world_id, owner_id, name, level, created_at, settled_at, cell_id, is_capital)
           VALUES (%s, 1, %s, %s, 0, %s, %s, %s, true)""",
        (city_id, player_id, normalized_name, now, now, cell_id),
    )
    entry(conn, city_id, STARTING_ALLOY, "genesis", f"genesis:{city_id}", now)
    result = {"id": str(city_id), "name": normalized_name, "cell_id": cell_id, "is_capital": True}
    save_idempotency(conn, player_id, key, "found_colony", fingerprint, result, now)
    return result


def city_state(conn, city, world, settled_at):
    count = extractor_count(conn, city["id"])
    cell = None
    if city["cell_id"] is not None:
        cell = conn.execute("SELECT id, q, r, terrain FROM world_cells WHERE id = %s", (city["cell_id"],)).fetchone()
    return {
        "id": city["id"], "name": city["name"], "level": city["level"],
        "is_capital": city["is_capital"], "cell": cell, "extractors": count,
        "production_milli_per_second": str(production_rate(world["policy"], city["level"], count)),
        "alloy_milli": str(balance(conn, city["id"])), "settled_at": settled_at,
        "policy": world["policy"], "next_tick_at": world["next_tick_at"],
    }


def read_city(conn, city_id, owner_id):
    world = lock_world(conn)
    city = owned_city(conn, city_id, owner_id)
    now = database_now(conn)
    require_current(world, now)
    settle(conn, city, now, world["policy"])
    return city_state(conn, city, world, now)


def build_extractor(conn, city_id, player_id, key):
    fingerprint = payload_hash({"city_id": str(city_id), "kind": "extractor"})
    world = lock_world(conn)
    city = owned_city(conn, city_id, player_id)
    replay = idempotency_replay(conn, player_id, key, "build_extractor", fingerprint)
    if replay is not None:
        return replay
    now = database_now(conn)
    require_current(world, now)
    settle(conn, city, now, world["policy"])
    if balance(conn, city_id) < EXTRACTOR_COST:
        raise DomainError(409, "Insufficient alloy for an extractor")
    building_id = uuid4()
    result = {
        "id": str(building_id), "city_id": str(city_id), "kind": "extractor",
        "cost_milli": str(EXTRACTOR_COST), "built_at": now.isoformat(),
    }
    action_id = save_idempotency(conn, player_id, key, "build_extractor", fingerprint, result, now)
    conn.execute(
        "INSERT INTO city_buildings(id, city_id, kind, built_at, action_id) VALUES (%s, %s, 'extractor', %s, %s)",
        (building_id, city_id, now, action_id),
    )
    entry(conn, city_id, -EXTRACTOR_COST, "extractor", f"extractor:{building_id}", now)
    return result


def submit_order(conn, city_id, owner_id, key, kind, choice):
    fingerprint = payload_hash({"choice": choice, "city_id": str(city_id), "kind": kind})
    world = lock_world(conn)
    city = owned_city(conn, city_id, owner_id)
    replay = idempotency_replay(conn, owner_id, key, "strategic_order", fingerprint)
    if replay is not None:
        return conn.execute("SELECT * FROM orders WHERE id = %s", (int(replay["order_id"]),)).fetchone()
    previous = conn.execute(
        "SELECT * FROM orders WHERE city_id = %s AND idempotency_key = %s", (city_id, key)
    ).fetchone()
    now = database_now(conn)
    if previous:
        if (previous["kind"], previous["choice"]) != (kind, choice):
            raise DomainError(409, "Idempotency key was already used with a different payload")
        save_idempotency(conn, owner_id, key, "strategic_order", fingerprint, {"order_id": str(previous["id"])}, now)
        return previous
    require_current(world, now)
    target = world["last_tick"] + 1
    if conn.execute(
        "SELECT 1 FROM orders WHERE city_id = %s AND target_tick = %s AND kind = %s",
        (city_id, target, kind),
    ).fetchone():
        raise DomainError(409, "This city already submitted this order type for the tick")
    settle(conn, city, now, world["policy"])
    order = conn.execute(
        """INSERT INTO orders(city_id, idempotency_key, kind, choice, target_tick, submitted_at)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (city_id, key, kind, choice, target, now),
    ).fetchone()
    save_idempotency(conn, owner_id, key, "strategic_order", fingerprint, {"order_id": str(order["id"])}, now)
    return order


def run_tick(conn):
    """One tick per transaction. Caller commits; retry is safe after any failure."""
    world = lock_world(conn)
    if database_now(conn) < world["next_tick_at"]:
        return None
    due, number = world["next_tick_at"], world["last_tick"] + 1
    cities = conn.execute("SELECT * FROM cities ORDER BY id").fetchall()
    for city in cities:
        settle(conn, city, due, world["policy"])
    orders = conn.execute(
        "SELECT * FROM orders WHERE target_tick = %s AND status = 'pending' ORDER BY id", (number,)
    ).fetchall()
    votes = {}
    applied = rejected = 0
    for order in orders:
        status, outcome = "applied", "vote_counted"
        if order["kind"] == "policy_vote":
            votes[order["choice"]] = votes.get(order["choice"], 0) + 1
        else:
            level = conn.execute("SELECT level FROM cities WHERE id = %s", (order["city_id"],)).fetchone()["level"]
            if level >= MAX_LEVEL:
                status, outcome = "rejected", "maximum_level"
            elif balance(conn, order["city_id"]) < UPGRADE_COST:
                status, outcome = "rejected", "insufficient_alloy"
            else:
                entry(conn, order["city_id"], -UPGRADE_COST, "upgrade", f"upgrade:{order['id']}", due)
                conn.execute("UPDATE cities SET level = level + 1 WHERE id = %s", (order["city_id"],))
                outcome = "level_increased"
        conn.execute("UPDATE orders SET status = %s, outcome = %s WHERE id = %s", (status, outcome, order["id"]))
        applied += status == "applied"
        rejected += status == "rejected"
    policy = elected_policy(world["policy"], votes)
    summary = {
        "policy_before": world["policy"], "policy_after": policy,
        "cities_settled": len(cities), "applied": applied, "rejected": rejected, "votes": votes,
    }
    conn.execute(
        "INSERT INTO ticks(number, due_at, ruleset, summary) VALUES (%s, %s, %s, %s)",
        (number, due, RULESET, Jsonb(summary)),
    )
    conn.execute(
        "UPDATE world SET last_tick = %s, next_tick_at = %s, policy = %s WHERE id = 1",
        (number, due + timedelta(days=1), policy),
    )
    return {"number": number, "due_at": due, **summary}
