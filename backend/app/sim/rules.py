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
    MAX_LEVEL, RESOURCES, food_income, food_upkeep, harvest_rate, production_rate,
    store_cap, supported_level, upgrade_cost, upgrade_duration,
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


def resource_rate(resource: str, policy: str, city: CityState) -> int:
    """Milli-unita' al secondo di una risorsa, per questa citta' sotto questa politica.

    UN intero per l'intera fetta su cui viene usato. E' la stessa regola che ha permesso di
    togliere il tick: se il tasso non e' costante dentro la fetta, spezzare un intervallo
    smette di dare lo stesso totale, e la produzione non puo' piu' maturare dai timestamp.
    """
    if resource == "food":
        # La terra da' quello che da'; le bocche si moltiplicano col livello. Da qui il tetto
        # vero della colonia, ed e' garantito positivo da `supported_level`.
        return food_income(city.site_food, policy) - food_upkeep(city.level)
    site = {"timber": city.site_timber, "stone": city.site_stone}[resource]
    return harvest_rate(resource, city.level, site, policy)


def settle_city(
    city: CityState, until: datetime, periods: list[PolicyPeriod]
) -> Settlement | None:
    """Mature this city's stores up to `until`. None when the cursor is already there.

    Every store is CAPPED, and a full one stops earning -- nothing is lost, the gaining
    stops. The clamp is applied inside each policy period rather than at the end, because a
    store that filled up on Tuesday must not go on earning at Wednesday's different rate.

    No event timeline is needed for this: every rate here is non-negative (food's is, because
    over-growing is refused rather than punished), so a store that is full stays full. The
    moment chains begin to CONSUME, that stops being true and this becomes an integration
    over events -- which is exactly why `time_to_full` already exists.
    """
    _whole_seconds(city.settled_at, until)
    if until < city.settled_at:
        raise ValueError("Invalid production interval")
    if until == city.settled_at:
        return None

    cap = store_cap(city.level)
    stock = dict(city.stock)
    gained = {resource: 0 for resource in RESOURCES}

    covered = 0
    for period in periods:
        slice_start = max(city.settled_at, period.from_at)
        slice_end = until if period.to_at is None else min(until, period.to_at)
        if slice_end <= slice_start:
            continue
        elapsed = slice_end - slice_start
        seconds = elapsed.days * 86400 + elapsed.seconds
        covered += seconds
        for resource in RESOURCES:
            held = stock.get(resource, 0)
            room_left = cap - held
            if room_left <= 0:
                continue
            amount = min(resource_rate(resource, period.policy, city) * seconds, room_left)
            if amount <= 0:
                continue
            stock[resource] = held + amount
            gained[resource] += amount

    whole = until - city.settled_at
    if covered != whole.days * 86400 + whole.seconds:
        raise ValueError("Policy timeline does not cover the production interval")

    entries = tuple(
        LedgerEntry(city.id, amount, "production",
                    f"production:{city.id}:{resource}:"
                    f"{city.settled_at.isoformat()}:{until.isoformat()}",
                    until, resource)
        for resource, amount in sorted(gained.items()) if amount
    )
    return Settlement(city=replace(city, settled_at=until, stock=stock), entries=entries)


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
) -> tuple[tuple[LedgerEntry, ...], datetime] | str:
    """Start an upgrade, or say in one word why not.

    The materials leave now: committing IS spending, so a city cannot queue four upgrades out
    of one store and cannot take the stone back out from under a commitment already running.
    What it buys is a moment in the future, and until then it is busy.

    The food check is a REFUSAL and not a punishment. A colony that grew past what its ground
    feeds would starve with no way back, and landing is irreversible -- so the level that
    cannot be fed is the level that cannot be started. It is measured against the least
    favourable policy, because the majority votes on how fast everyone goes, not on who
    survives.
    """
    _whole_seconds(now)
    if busy:
        return "already_busy"
    if city.level >= MAX_LEVEL:
        return "maximum_level"
    if city.level + 1 > supported_level(city.site_food):
        return "not_enough_food"
    cost = upgrade_cost(city.level, city.site_room)
    for resource, amount in sorted(cost.items()):
        if city.stock.get(resource, 0) < amount:
            return f"insufficient_{resource}"
    entries = tuple(
        LedgerEntry(city.id, -amount, "upgrade",
                    f"upgrade:{city.id}:{resource}:{now.isoformat()}", now, resource)
        for resource, amount in sorted(cost.items())
    )
    return entries, now + upgrade_duration(city.level, city.site_effort, city.site_room)
