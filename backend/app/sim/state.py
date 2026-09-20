"""The simulation's state and its effects, as plain frozen values.

Nothing here knows about PostgreSQL, HTTP or React. That is the whole point: the rules in
`rules.py` take these values and return new ones, so they can be exercised without a
database, replayed from a snapshot, and one day re-implemented in another engine without
first having to be reverse-engineered out of SQL.

Two kinds live here, and the distinction matters:

* **state**  -- `CityState`, `Commitment`, `PolicyPeriod`: what is true right now;
* **effects** -- `LedgerEntry`, `Settlement`, `Completion`, `Advance`: what a rule decided
  should happen. A rule never writes; it describes. The adapter in `app/service.py` is the
  only code that turns a described effect into a row.
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
class Commitment:
    """Something a city is busy with. The cost is already paid -- committing is spending --
    and `completes_at` is a moment in world time, not a number of ticks away."""
    id: int
    city_id: UUID
    kind: str
    completes_at: datetime


@dataclass(frozen=True)
class PolicyPeriod:
    """A stretch of world time during which one policy was in force. `to_at` is None for the
    period still running.

    Policy is a timeline rather than a single current value because production is worked out
    over an interval: a city settling a week's worth has to be paid at the rates those days
    actually had. The tick used to guarantee that by settling every city at the boundary
    before letting the new policy start -- which is a global barrier, and the reason this is
    a table instead.
    """
    policy: str
    from_at: datetime
    to_at: datetime | None


@dataclass(frozen=True)
class LedgerEntry:
    """A described ledger movement. `event_key` is what makes applying it twice impossible:
    the database rejects a duplicate, so a retried operation cannot mint or spend a second
    time."""
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
class Completion:
    """A commitment that came due. The alloy was spent when it started, so finishing only
    changes the city -- there is no second ledger movement."""
    commitment_id: int
    outcome: str
    level_after: int


@dataclass(frozen=True)
class Advance:
    """Everything that happened to ONE city between its cursor and now.

    Per city, deliberately. The world is shared and persistent and different players' cities
    are meant to proceed in parallel; a rule that demanded the whole world would quietly undo
    that, because every read of one city would have to load, and therefore lock, all of them.
    """
    city: CityState
    settlements: tuple[Settlement, ...]
    completions: tuple[Completion, ...]

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(s.entry for s in self.settlements if s.entry is not None)


def snapshot(policy: str, cities: tuple[CityState, ...] | list[CityState]) -> dict:
    """A JSON-able picture of the simulation state, stamped with the ruleset that governs it.

    This is a debugging and comparison tool, not a save file: the authoritative world lives
    in PostgreSQL and is versioned by its migrations, so there is deliberately no second
    persistence format to keep in step. What this buys is the ability to diff two worlds, to
    feed a known state into a test, and to hand the state to another engine later.
    """
    return {
        "ruleset": RULESET,
        "world": {"policy": policy},
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
