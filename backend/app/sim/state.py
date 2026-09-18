"""The simulation's state and its effects, as plain frozen values.

Nothing here knows about PostgreSQL, HTTP or React. That is the whole point: the rules in
`rules.py` and `tick.py` take these values and return new ones, so they can be exercised
without a database, replayed from a snapshot, and one day re-implemented in another engine
without first having to be reverse-engineered out of SQL.

Two kinds live here, and the distinction matters:

* **state**  -- `WorldState`, `CityState`, `OrderState`: what is true right now;
* **effects** -- `LedgerEntry`, `Settlement`, `OrderResolution`, `TickResult`: what a rule
  decided should happen. A rule never writes; it describes. The adapter in `app/service.py`
  is the only code that turns a described effect into a row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.sim.config import RULESET


@dataclass(frozen=True)
class CityState:
    """One settlement. `balance_milli` mirrors the ledger sum, which the database keeps
    materialised; the rules read it so they never have to scan a ledger to know a balance."""
    id: UUID
    level: int
    balance_milli: int
    settled_at: datetime


@dataclass(frozen=True)
class WorldState:
    policy: str
    last_tick: int
    next_tick_at: datetime


@dataclass(frozen=True)
class OrderState:
    id: int
    city_id: UUID
    kind: str
    choice: str | None


@dataclass(frozen=True)
class LedgerEntry:
    """A described ledger movement. `event_key` is what makes applying it twice impossible:
    the database rejects a duplicate, so a retried tick cannot mint or spend a second time."""
    city_id: UUID
    amount: int
    reason: str
    event_key: str
    effective_at: datetime


@dataclass(frozen=True)
class Settlement:
    """Production matured up to a moment. `city` is the city after settling; `entry` is None
    when the elapsed time produced nothing but the cursor still has to move."""
    city: CityState
    entry: LedgerEntry | None


@dataclass(frozen=True)
class OrderResolution:
    order_id: int
    city_id: UUID
    status: str
    outcome: str
    entry: LedgerEntry | None
    level_after: int | None


@dataclass(frozen=True)
class TickResult:
    number: int
    due_at: datetime
    next_tick_at: datetime
    policy_before: str
    policy_after: str
    cities_settled: int
    settlements: tuple[Settlement, ...]
    resolutions: tuple[OrderResolution, ...]
    votes: dict[str, int]
    applied: int
    rejected: int

    @property
    def summary(self) -> dict:
        """What gets recorded on the tick row: the outcome, without the row-level effects."""
        return {
            "policy_before": self.policy_before,
            "policy_after": self.policy_after,
            "cities_settled": self.cities_settled,
            "applied": self.applied,
            "rejected": self.rejected,
            "votes": self.votes,
        }


def snapshot(world: WorldState, cities: tuple[CityState, ...] | list[CityState]) -> dict:
    """A JSON-able picture of the simulation state, stamped with the ruleset that governs it.

    This is a debugging and comparison tool, not a save file: the authoritative world lives
    in PostgreSQL and is versioned by its migrations, so there is deliberately no second
    persistence format to keep in step. What this buys is the ability to diff two worlds,
    to feed a known state into a test, and to hand the state to another engine later.
    """
    return {
        "ruleset": RULESET,
        "world": {
            "policy": world.policy,
            "last_tick": world.last_tick,
            "next_tick_at": world.next_tick_at.isoformat(),
        },
        "cities": [
            {
                "id": str(city.id),
                "level": city.level,
                "balance_milli": city.balance_milli,
                "settled_at": city.settled_at.isoformat(),
            }
            for city in cities
        ],
    }
