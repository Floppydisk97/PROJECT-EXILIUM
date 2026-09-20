"""The rules of ruleset 2: pure functions from state to described effects.

These are deliberately per-entity rather than one function over the whole world. The world is
shared and persistent, and different players' cities are meant to proceed in parallel -- they
serialise only on their own row, never on each other. A rule that demanded the entire world as
its argument would quietly undo that: every read of one city would have to load, and therefore
lock, all of them.

There used to be one exception, the tick, which held the world exclusively because it settled
every city at once. It is gone, and with it the barrier. What made that possible is that
policy became a timeline instead of a single current value -- see `production_amount`.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from app.sim.config import (
    MAX_LEVEL, production_rate, upgrade_cost, upgrade_duration,
)
from app.sim.state import (
    Advance, CityState, Commitment, Completion, LedgerEntry, PolicyPeriod, Settlement,
)


def _whole_seconds(*moments: datetime) -> None:
    for moment in moments:
        if moment.tzinfo is None:
            raise ValueError("Timezone-aware timestamps required")
        if moment.microsecond:
            raise ValueError("Production timestamps must have whole-second precision")


def production_amount(
    start: datetime, end: datetime, periods: list[PolicyPeriod], level: int,
    site_food: int = 0,
) -> int:
    """Milli-alloy matured over an interval, integrated across the policies it crosses.

    Integer arithmetic at one-second granularity, so splitting an interval anywhere gives the
    same total as not splitting it -- which is what lets production accrue during downtime
    without a job running every second.

    The periods argument is the whole reason the tick could be removed. Production is paid at
    the rate the time actually had; with one policy per call, the only way to guarantee that
    was to settle every city at the moment of a change, before letting the new rate start.
    That is a global barrier. Integrating instead means a city works out its own history, when
    somebody looks at it, without holding anyone else still.

    An interval not covered by any period is a bug rather than free alloy, so it is refused.

    `site_food` is the colony's ground, and it multiplies the rate rather than the total:
    the rate has to be one integer per slice, or splitting an interval would not give the
    same answer as not splitting it.
    """
    _whole_seconds(start, end)
    if end < start or level < 0:
        raise ValueError("Invalid production interval or level")
    if end == start:
        return 0

    total = 0
    covered = 0
    for period in periods:
        slice_start = max(start, period.from_at)
        slice_end = end if period.to_at is None else min(end, period.to_at)
        if slice_end <= slice_start:
            continue
        elapsed = slice_end - slice_start
        seconds = elapsed.days * 86400 + elapsed.seconds
        covered += seconds
        total += seconds * production_rate(period.policy, level, site_food)

    whole = end - start
    if covered != whole.days * 86400 + whole.seconds:
        raise ValueError("Policy timeline does not cover the production interval")
    return total


def majority_policy(current: str, votes: dict[str, int]) -> str:
    """Simple majority, one standing vote per city. A tie or an empty ballot keeps what is in
    force: a vote nobody contested must not be able to change anything.

    Continuous now rather than counted at a boundary -- a city holds its preference and the
    majority is whatever the held preferences currently say.
    """
    balanced = votes.get("balanced", 0)
    industrial = votes.get("industrial", 0)
    if balanced == industrial:
        return current
    return "balanced" if balanced > industrial else "industrial"


def settle_city(
    city: CityState, until: datetime, periods: list[PolicyPeriod]
) -> Settlement | None:
    """Mature this city's production up to `until`. None when the cursor is already there.

    The amount is computed before that check on purpose: an invalid timestamp has to be
    rejected whether or not there is anything to settle, or a bad clock would pass silently in
    exactly the case where nothing looks wrong.
    """
    amount = production_amount(city.settled_at, until, periods, city.level, city.site_food)
    if until == city.settled_at:
        return None
    entry = None
    if amount:
        key = f"production:{city.id}:{city.settled_at.isoformat()}:{until.isoformat()}"
        entry = LedgerEntry(city.id, amount, "production", key, until)
    return Settlement(
        city=replace(city, settled_at=until, balance_milli=city.balance_milli + amount),
        entry=entry,
    )


def advance_city(
    city: CityState,
    commitment: Commitment | None,
    periods: list[PolicyPeriod],
    now: datetime,
) -> Advance:
    """Everything that has happened to one city between its cursor and now.

    The order is the rule, not an implementation detail. A commitment that came due at some
    point in the middle splits the interval: production before it is earned at the OLD level,
    the commitment then completes, and production after it is earned at the new one. Settling
    the whole stretch first and raising the level afterwards would pay the past at a rate the
    past did not have -- the same mistake the tick's boundary existed to prevent, which does
    not stop being a mistake just because the boundary is gone.
    """
    _whole_seconds(now)
    settlements: list[Settlement] = []
    completions: list[Completion] = []

    if commitment is not None and commitment.completes_at <= now:
        settlement = settle_city(city, commitment.completes_at, periods)
        if settlement is not None:
            settlements.append(settlement)
            city = settlement.city
        city = replace(city, level=city.level + 1)
        completions.append(Completion(commitment.id, "level_increased", city.level))

    settlement = settle_city(city, now, periods)
    if settlement is not None:
        settlements.append(settlement)
        city = settlement.city

    return Advance(city=city, settlements=tuple(settlements), completions=tuple(completions))


def begin_upgrade(
    city: CityState, busy: bool, now: datetime
) -> tuple[LedgerEntry, datetime] | str:
    """Start an upgrade, or say in one word why not.

    The alloy leaves now: committing IS spending, so a city cannot queue four upgrades out of
    one balance and it cannot take the alloy back out from under a commitment already running.
    What the city buys is a moment in the future, and until then it is busy -- which is the
    whole of the new economy's scarcity. There is no queue to be limited, because the limit is
    that a city does one thing at a time.
    """
    _whole_seconds(now)
    if busy:
        return "already_busy"
    if city.level >= MAX_LEVEL:
        return "maximum_level"
    cost = upgrade_cost(city.level, city.site_room)
    if city.balance_milli < cost:
        return "insufficient_alloy"
    entry = LedgerEntry(city.id, -cost, "upgrade", f"upgrade:{city.id}:{now.isoformat()}", now)
    return entry, now + upgrade_duration(city.level, city.site_effort, city.site_room)
