"""The adapter between the simulation and the database.

Every rule of the game lives in `app/sim/`, which cannot see PostgreSQL. This module is the
seam: it loads rows into simulation state, asks the rules what should happen, and writes the
described effects back inside one transaction. It also owns what is genuinely the database's
job and not the simulation's -- locking, authorisation, idempotency and the clock.

THE LOCK MODEL, which is the whole reason the rules are per-entity.

There is no global barrier any more. A city is advanced under a lock on its OWN row: two
requests touching the same city serialise, and two touching different cities do not meet at
all. The tick used to take `world FOR UPDATE` and settle everybody at once, which is what put
a ceiling on how many players the world could hold.

What is left of the world row is the policy timeline, and it is locked only when the majority
actually changes -- a short lock on a handful of rows, not a stall over every city.
"""
import hashlib
import secrets
from uuid import uuid4

from app import db
from app.sim import CityState, Commitment, PolicyPeriod, advance_city, begin_upgrade
from app.sim.config import RULESET, STARTING_ALLOY, upgrade_cost, upgrade_duration
from app.sim.rules import majority_policy


class DomainError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def owned_city(conn, city_id, owner_id, lock=False):
    # lock=True takes a row lock on this city only: concurrent advances of the SAME city
    # serialize (no duplicate production, no two commitments), while different cities proceed
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
        """INSERT INTO resource_ledger(city_id, amount, reason, event_key, effective_at, ruleset)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (city_id, amount, reason, event_key, effective_at, RULESET),
    )


def write_entry(conn, described):
    entry(conn, described.city_id, described.amount, described.reason,
          described.event_key, described.effective_at)


def city_state(row) -> CityState:
    """A database row as the simulation sees it: nothing about ownership or naming, which
    are the adapter's business, and no column the rules do not actually read."""
    return CityState(
        id=row["id"],
        level=row["level"],
        balance_milli=int(row["balance_milli"]),
        settled_at=row["settled_at"],
    )


def policy_periods(conn, since) -> list[PolicyPeriod]:
    """The policy timeline covering everything from `since` onwards.

    Only the periods a city still has to settle across are loaded, which is normally one.
    A world whose policy changes daily and a city untouched for a year would load a year of
    them -- bounded by how often the majority actually moves, not by how many cities exist.
    """
    rows = conn.execute(
        """SELECT policy, from_at, to_at FROM policy_periods
           WHERE to_at IS NULL OR to_at > %s
           ORDER BY from_at""",
        (since,),
    ).fetchall()
    return [PolicyPeriod(r["policy"], r["from_at"], r["to_at"]) for r in rows]


def current_policy(conn) -> str:
    return conn.execute(
        "SELECT policy FROM policy_periods WHERE to_at IS NULL"
    ).fetchone()["policy"]


def commitment_of(conn, city_id) -> Commitment | None:
    row = conn.execute(
        "SELECT id, city_id, kind, completes_at FROM orders "
        "WHERE city_id = %s AND status = 'pending'",
        (city_id,),
    ).fetchone()
    return None if row is None else Commitment(
        row["id"], row["city_id"], row["kind"], row["completes_at"]
    )


def advance(conn, city_row, now):
    """Bring one city up to `now`: finish what came due, then mature its production.

    This is what the tick was, narrowed to a single city. It runs lazily -- whenever somebody
    looks at the city or asks it to do something -- so a world with nobody watching costs
    nothing and a city nobody touches is still correct the moment it is read.
    """
    city = city_state(city_row)
    result = advance_city(
        city, commitment_of(conn, city_row["id"]), policy_periods(conn, city.settled_at), now
    )
    for settlement in result.settlements:
        if settlement.entry is not None:
            write_entry(conn, settlement.entry)
    for completion in result.completions:
        conn.execute(
            "UPDATE orders SET status = 'applied', outcome = %s WHERE id = %s",
            (completion.outcome, completion.commitment_id),
        )
    if result.settlements or result.completions:
        conn.execute(
            "UPDATE cities SET settled_at = %s, level = %s WHERE id = %s",
            (result.city.settled_at, result.city.level, result.city.id),
        )
    return result


def provision(conn, name):
    if not 1 <= len(name.strip()) <= 80:
        raise DomainError(422, "City name must contain 1-80 characters")
    now = db.database_now(conn)
    owner, city, token = uuid4(), uuid4(), secrets.token_urlsafe(32)
    conn.execute("INSERT INTO players VALUES (%s, %s, %s)", (owner, token_hash(token), now))
    conn.execute(
        "INSERT INTO cities(id, owner_id, name, created_at, settled_at) VALUES (%s, %s, %s, %s, %s)",
        (city, owner, name.strip(), now, now),
    )
    entry(conn, city, STARTING_ALLOY, "genesis", f"genesis:{city}", now)
    return {"player_id": owner, "city_id": city, "token": token}


def city_view(conn, city_row, now) -> dict:
    busy = commitment_of(conn, city_row["id"])
    level = city_row["level"]
    return {
        "id": city_row["id"], "name": city_row["name"], "level": level,
        "alloy_milli": str(balance(conn, city_row["id"])),
        "settled_at": now,
        "policy": current_policy(conn),
        "policy_vote": city_row["policy_vote"],
        # What it would take to start the next upgrade, so a client never has to know the
        # curve: the rules own it and say so.
        "next_upgrade_cost_milli": str(upgrade_cost(level)),
        "next_upgrade_seconds": int(upgrade_duration(level).total_seconds()),
        "busy_until": None if busy is None else busy.completes_at,
        "busy_with": None if busy is None else busy.kind,
    }


def read_city(conn, city_id, owner_id):
    city = owned_city(conn, city_id, owner_id, lock=True)
    now = db.database_now(conn)
    advance(conn, city, now)
    return city_view(conn, owned_city(conn, city_id, owner_id), now)


def start_upgrade(conn, city_id, owner_id, key):
    """Commit this city to an upgrade. The alloy goes now; the level arrives later.

    Idempotent on `key`, because a retried request must not spend twice -- the same guarantee
    the order queue used to give, kept now that there is no queue.
    """
    city_row = owned_city(conn, city_id, owner_id, lock=True)
    previous = conn.execute(
        "SELECT * FROM orders WHERE city_id = %s AND idempotency_key = %s", (city_id, key)
    ).fetchone()
    if previous:
        return previous

    now = db.database_now(conn)
    result = advance(conn, city_row, now)
    decision = begin_upgrade(result.city, commitment_of(conn, city_id) is not None, now)
    if isinstance(decision, str):
        raise DomainError(409, decision)
    spend, completes_at = decision
    write_entry(conn, spend)
    return conn.execute(
        """INSERT INTO orders(city_id, idempotency_key, kind, choice, submitted_at,
                              completes_at, cost_milli)
           VALUES (%s, %s, 'upgrade', NULL, %s, %s, %s) RETURNING *""",
        (city_id, key, now, completes_at, -spend.amount),
    ).fetchone()


def cast_vote(conn, city_id, owner_id, choice):
    """Set this city's standing preference and, if the majority moved, close the current
    policy period and open a new one.

    The world row is locked for the length of that decision so two votes cannot both think
    they flipped it. It is one row, held for one statement -- not the old barrier, which held
    every city still for as long as it took to settle all of them.
    """
    if choice not in ("balanced", "industrial"):
        raise DomainError(422, "Vote must be 'balanced' or 'industrial'")
    owned_city(conn, city_id, owner_id, lock=True)
    conn.execute("SELECT 1 FROM world WHERE id = 1 FOR UPDATE")
    conn.execute("UPDATE cities SET policy_vote = %s WHERE id = %s", (choice, city_id))

    votes = {
        row["policy_vote"]: int(row["n"]) for row in conn.execute(
            "SELECT policy_vote, count(*) AS n FROM cities "
            "WHERE policy_vote IS NOT NULL GROUP BY policy_vote"
        ).fetchall()
    }
    standing = current_policy(conn)
    elected = majority_policy(standing, votes)
    if elected != standing:
        now = db.database_now(conn)
        open_from = conn.execute(
            "SELECT from_at FROM policy_periods WHERE to_at IS NULL"
        ).fetchone()["from_at"]
        if open_from == now:
            # Two changes inside the same second. A period of zero length is not a period --
            # it would cover no production and could not be told apart from the one it
            # replaced -- so the standing one is corrected rather than closed and reopened.
            conn.execute(
                "UPDATE policy_periods SET policy = %s WHERE to_at IS NULL", (elected,)
            )
        else:
            conn.execute("UPDATE policy_periods SET to_at = %s WHERE to_at IS NULL", (now,))
            conn.execute(
                "INSERT INTO policy_periods(policy, from_at) VALUES (%s, %s)", (elected, now)
            )
    return {"policy_vote": choice, "policy": elected, "votes": votes}
