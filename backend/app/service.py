"""The adapter between the simulation and the database.

Every rule of the game lives in `app/sim/`, which cannot see PostgreSQL. This module is the
seam: it loads rows into simulation state, asks the rules what should happen, and writes the
described effects back inside one transaction. It also owns what is genuinely the database's
job and not the simulation's -- locking, authorisation, idempotency and the clock.

The lock model is deliberate and is the reason the rules are per-entity rather than global.
Economic operations take `world FOR SHARE`: they proceed in parallel with each other but not
with a tick, and they serialise only on their own city row. The tick takes `world FOR UPDATE`
and observes a quiescent world.
"""
import hashlib
import secrets
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.db import database_now
from app.sim import CityState, OrderState, WorldState, advance
from app.sim.config import RULESET, STARTING_ALLOY
from app.sim.rules import settle_city


class DomainError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def lock_world(conn):
    # Exclusive lock: the tick barrier. Blocks and is blocked by every economic
    # operation, so a tick observes a quiescent world and no settlement is mid-flight.
    return conn.execute("SELECT * FROM world WHERE id = 1 FOR UPDATE").fetchone()


def read_world(conn):
    # Shared lock: economic operations only need the world to hold still (no tick
    # running) while they act. Many run in parallel; they serialize per city on the
    # city row, not globally. FOR SHARE still conflicts with the tick's FOR UPDATE.
    return conn.execute("SELECT * FROM world WHERE id = 1 FOR SHARE").fetchone()


def require_current(world, now):
    if now >= world["next_tick_at"]:
        raise DomainError(503, "World tick pending; retry after recovery")


def owned_city(conn, city_id, owner_id, lock=False):
    # lock=True takes a row lock on this city only: concurrent settlements of the
    # SAME city serialize (no duplicate production), while different cities proceed
    # in parallel. Read-only authorization checks pass lock=False.
    suffix = " FOR UPDATE" if lock else ""
    city = conn.execute(
        "SELECT * FROM cities WHERE id = %s AND owner_id = %s" + suffix, (city_id, owner_id)
    ).fetchone()
    if city is None:
        raise DomainError(404, "City not found")
    return city


def balance(conn, city_id):
    # O(1) read of the materialized cursor. The ledger trigger keeps it exactly
    # equal to SUM(resource_ledger.amount); test_materialized_balance_* guards it.
    return int(conn.execute(
        "SELECT balance_milli FROM cities WHERE id = %s", (city_id,)
    ).fetchone()["balance_milli"])


def entry(conn, city_id, amount, reason, event_key, effective_at):
    conn.execute(
        """INSERT INTO resource_ledger(city_id, amount, reason, event_key, effective_at)
           VALUES (%s, %s, %s, %s, %s)""",
        (city_id, amount, reason, event_key, effective_at),
    )


def city_state(row) -> CityState:
    """A database row as the simulation sees it: nothing about ownership or naming, which
    are the adapter's business, and no column the rules do not actually read."""
    return CityState(
        id=row["id"],
        level=row["level"],
        balance_milli=int(row["balance_milli"]),
        settled_at=row["settled_at"],
    )


def world_state(row) -> WorldState:
    return WorldState(
        policy=row["policy"], last_tick=row["last_tick"], next_tick_at=row["next_tick_at"]
    )


def write_entry(conn, described):
    entry(conn, described.city_id, described.amount, described.reason,
          described.event_key, described.effective_at)


def settle(conn, city, until, policy):
    """Apply the settlement the rules describe for this one city."""
    settlement = settle_city(city_state(city), until, policy)
    if settlement is None:
        return
    if settlement.entry is not None:
        write_entry(conn, settlement.entry)
    conn.execute("UPDATE cities SET settled_at = %s WHERE id = %s", (until, city["id"]))


def provision(conn, name):
    if not 1 <= len(name.strip()) <= 80:
        raise DomainError(422, "City name must contain 1-80 characters")
    world = read_world(conn)
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
    world = read_world(conn)
    city = owned_city(conn, city_id, owner_id, lock=True)
    now = database_now(conn)
    require_current(world, now)
    settle(conn, city, now, world["policy"])
    return {
        "id": city["id"], "name": city["name"], "level": city["level"],
        "alloy_milli": str(balance(conn, city_id)), "settled_at": now,
        "policy": world["policy"], "next_tick_at": world["next_tick_at"],
    }


def submit_order(conn, city_id, owner_id, key, kind, choice):
    world = read_world(conn)
    city = owned_city(conn, city_id, owner_id, lock=True)
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
    """One tick per transaction. Caller commits; retry is safe after any failure.

    The decision is made entirely by `sim.advance`, which touches nothing. What is left here
    is loading the inputs under the world lock and writing the described effects -- in the
    same order the rules described them, so a failure part-way leaves the transaction to roll
    back a coherent prefix rather than an arbitrary one.
    """
    world_row = lock_world(conn)
    if database_now(conn) < world_row["next_tick_at"]:
        return None
    world = world_state(world_row)
    cities = [
        city_state(row)
        for row in conn.execute("SELECT * FROM cities ORDER BY id").fetchall()
    ]
    orders = [
        OrderState(id=row["id"], city_id=row["city_id"], kind=row["kind"], choice=row["choice"])
        for row in conn.execute(
            "SELECT * FROM orders WHERE target_tick = %s AND status = 'pending' ORDER BY id",
            (world.last_tick + 1,),
        ).fetchall()
    ]

    result = advance(world, cities, orders, world.next_tick_at)

    for settlement in result.settlements:
        if settlement.entry is not None:
            write_entry(conn, settlement.entry)
        conn.execute(
            "UPDATE cities SET settled_at = %s WHERE id = %s",
            (settlement.city.settled_at, settlement.city.id),
        )
    for resolution in result.resolutions:
        if resolution.entry is not None:
            write_entry(conn, resolution.entry)
        if resolution.level_after is not None:
            conn.execute(
                "UPDATE cities SET level = %s WHERE id = %s",
                (resolution.level_after, resolution.city_id),
            )
        conn.execute(
            "UPDATE orders SET status = %s, outcome = %s WHERE id = %s",
            (resolution.status, resolution.outcome, resolution.order_id),
        )

    conn.execute(
        "INSERT INTO ticks(number, due_at, ruleset, summary) VALUES (%s, %s, %s, %s)",
        (result.number, result.due_at, RULESET, Jsonb(result.summary)),
    )
    conn.execute(
        "UPDATE world SET last_tick = %s, next_tick_at = %s, policy = %s WHERE id = 1",
        (result.number, result.next_tick_at, result.policy_after),
    )
    return {"number": result.number, "due_at": result.due_at, **result.summary}
