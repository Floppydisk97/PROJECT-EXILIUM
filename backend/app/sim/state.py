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

from dataclasses import dataclass, field
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from app.sim.config import RULESET


@dataclass(frozen=True)
class CityState:
    """One settlement. `stock` mirrors the ledger sums, which the database keeps materialised
    per resource; the rules read it so they never have to scan a ledger to know a store.

    The three site numbers are what the colony kept of its ground -- see `citygen.SiteEconomy`.
    They are fixed at landing and never change: the map is a function of the seed, and the
    seed does not move. Their defaults are what a colony still in orbit has, and they are
    chosen so that a city without ground produces exactly what it produced before there was
    any ground at all.
    """
    id: UUID
    level: int
    settled_at: datetime
    stock: Mapping[str, int] = field(default_factory=dict)
    # Le opere costruite, per tipo. Consumano e producono di continuo, e sono la ragione per
    # cui la produzione non e' piu' una moltiplicazione: un processo che CONSUMA puo'
    # rimanere a secco, e da quel momento il tasso non e' piu' quello di prima.
    works: Mapping[str, int] = field(default_factory=dict)
    site_food: int = 0             # 0 -> the rate is untouched
    site_timber: int = 0           # what the standing growth is worth once cleared
    site_stone: int = 0            # what is under the colony
    site_ore: int = 0              # i filoni: l'unico che non sta in superficie
    site_effort: int = 0           # 0 -> an upgrade takes its bare duration
    site_room: int | None = None   # None -> nothing to crowd against


@dataclass(frozen=True)
class Commitment:
    """Something a city is busy with. The cost is already paid -- committing is spending --
    and `completes_at` is a moment in world time, not a number of ticks away."""
    id: int
    city_id: UUID
    kind: str
    completes_at: datetime
    choice: str | None = None      # per un'opera: quale opera


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
    resource: str = "alloy"   # il default e' la risorsa del ruleset 2, che non si conia piu'


@dataclass(frozen=True)
class Settlement:
    """Production matured up to a moment. `city` is the city after settling; `entries` is
    empty when the elapsed time produced nothing but the cursor still has to move -- which
    now also happens when every store is full, because a full store stops earning."""
    city: CityState
    entries: tuple[LedgerEntry, ...] = ()


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
        return tuple(entry for s in self.settlements for entry in s.entries)


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
                "stock": dict(sorted(city.stock.items())),
                "works": dict(sorted(city.works.items())),
                "settled_at": city.settled_at.isoformat(),
                "site": {"food": city.site_food, "timber": city.site_timber,
                         "stone": city.site_stone, "effort": city.site_effort,
                         "room": city.site_room},
            }
            for city in cities
        ],
    }
