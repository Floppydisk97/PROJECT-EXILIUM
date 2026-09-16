import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.db import database_now
from app.domain import (
    MAX_LEVEL, RULESET, STARTING_ALLOY, UPGRADE_COST, elected_policy, production_amount,
)


class DomainError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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


def settle(conn, city, until, policy):
    amount = production_amount(city["settled_at"], until, policy, city["level"])
    if until == city["settled_at"]:
        return
    if amount:
        key = f"production:{city['id']}:{city['settled_at'].isoformat()}:{until.isoformat()}"
        entry(conn, city["id"], amount, "production", key, until)
    conn.execute("UPDATE cities SET settled_at = %s WHERE id = %s", (until, city["id"]))


def provision(conn, name):
    if not 1 <= len(name.strip()) <= 80:
        raise DomainError(422, "City name must contain 1-80 characters")
    world = lock_world(conn)
    now = database_now(conn)
    require_current(world, now)
    owner, city, token = uuid4(), uuid4(), secrets.token_urlsafe(32)
    conn.execute("INSERT INTO players VALUES (%s, %s, %s)", (owner, token_hash(token), now))
    conn.execute(
        "INSERT INTO cities(id, owner_id, name, created_at, settled_at) VALUES (%s, %s, %s, %s, %s)",
        (city, owner, name.strip(), now, now),
    )
    entry(conn, city, STARTING_ALLOY, "genesis", f"genesis:{city}", now)
    return {"player_id": owner, "city_id": city, "token": token}


def read_city(conn, city_id, owner_id):
    world = lock_world(conn)
    city = owned_city(conn, city_id, owner_id)
    now = database_now(conn)
    require_current(world, now)
    settle(conn, city, now, world["policy"])
    return {
        "id": city["id"], "name": city["name"], "level": city["level"],
        "alloy_milli": str(balance(conn, city_id)), "settled_at": now,
        "policy": world["policy"], "next_tick_at": world["next_tick_at"],
    }


def submit_order(conn, city_id, owner_id, key, kind, choice):
    world = lock_world(conn)
    city = owned_city(conn, city_id, owner_id)
    previous = conn.execute(
        "SELECT * FROM orders WHERE city_id = %s AND idempotency_key = %s", (city_id, key)
    ).fetchone()
    if previous:
        if (previous["kind"], previous["choice"]) != (kind, choice):
            raise DomainError(409, "Idempotency key already used for a different command")
        return previous
    now = database_now(conn)
    require_current(world, now)
    target = world["last_tick"] + 1
    exists = conn.execute(
        "SELECT 1 FROM orders WHERE city_id = %s AND target_tick = %s AND kind = %s",
        (city_id, target, kind),
    ).fetchone()
    if exists:
        raise DomainError(409, "This city already submitted this order type for the tick")
    settle(conn, city, now, world["policy"])
    return conn.execute(
        """INSERT INTO orders(city_id, idempotency_key, kind, choice, target_tick, submitted_at)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (city_id, key, kind, choice, target, now),
    ).fetchone()


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
