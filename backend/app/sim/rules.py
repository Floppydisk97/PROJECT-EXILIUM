"""The rules of ruleset 1: pure functions from state to described effects.

These are deliberately per-entity rather than one function over the whole world. The world
is shared and persistent, and different players' settlements are meant to proceed in
parallel -- they serialise only on their own row, never on each other. A rule that demanded
the entire world as its argument would quietly undo that: every read of one city would have
to load, and therefore lock, all of them. So settling is a rule about one city, and only the
tick -- which already holds the world exclusively -- is a rule about all of them.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from app.sim.config import LEVEL_RATE, MAX_LEVEL, POLICY_RATES, UPGRADE_COST
from app.sim.state import CityState, LedgerEntry, OrderResolution, OrderState, Settlement


def production_amount(start: datetime, end: datetime, policy: str, level: int) -> int:
    """Milli-alloy matured over an interval. Integer arithmetic at one-second granularity,
    so splitting an interval anywhere gives the same total as not splitting it -- which is
    what lets production accrue during downtime without a job running every second."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Timezone-aware timestamps required")
    if start.microsecond or end.microsecond:
        raise ValueError("Production timestamps must have whole-second precision")
    if end < start or level < 0:
        raise ValueError("Invalid production interval or level")
    elapsed = end - start
    seconds = elapsed.days * 86400 + elapsed.seconds
    return seconds * (POLICY_RATES[policy] + level * LEVEL_RATE)


def elected_policy(current: str, votes: dict[str, int]) -> str:
    """Simple majority, one vote per city. A tie or an empty ballot keeps the incumbent:
    an election that nobody contested must not be able to change anything."""
    balanced = votes.get("balanced", 0)
    industrial = votes.get("industrial", 0)
    if balanced == industrial:
        return current
    return "balanced" if balanced > industrial else "industrial"


def settle_city(city: CityState, until: datetime, policy: str) -> Settlement | None:
    """Mature this city's production up to `until`. None when the cursor is already there.

    The amount is computed before that check on purpose: an invalid timestamp has to be
    rejected whether or not there is anything to settle, or a bad clock would pass silently
    in exactly the case where nothing looks wrong.
    """
    amount = production_amount(city.settled_at, until, policy, city.level)
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


def resolve_order(
    order: OrderState, city: CityState, due: datetime
) -> tuple[OrderResolution, CityState]:
    """Decide one order against the city as it stands, and return the city as it stands after.

    Threading the city through is what keeps a sequence of orders honest: each one sees the
    balance the previous ones left, so an upgrade cannot be paid for twice out of the same
    alloy even if the rules later allow more than one order per city per tick.
    """
    if order.kind == "policy_vote":
        return OrderResolution(order.id, city.id, "applied", "vote_counted", None, None), city
    if city.level >= MAX_LEVEL:
        return OrderResolution(order.id, city.id, "rejected", "maximum_level", None, None), city
    if city.balance_milli < UPGRADE_COST:
        return OrderResolution(order.id, city.id, "rejected", "insufficient_alloy", None, None), city
    entry = LedgerEntry(city.id, -UPGRADE_COST, "upgrade", f"upgrade:{order.id}", due)
    city = replace(
        city, level=city.level + 1, balance_milli=city.balance_milli - UPGRADE_COST
    )
    return OrderResolution(
        order.id, city.id, "applied", "level_increased", entry, city.level
    ), city
