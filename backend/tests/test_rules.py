from datetime import UTC, datetime, timedelta

import pytest

from app.sim.config import (
    LEVEL_RATE, POLICY_RATES, ROOM_PER_LEVEL, UPGRADE_DURATION,
    production_rate, upgrade_cost, upgrade_duration,
)
from app.sim.rules import majority_policy, production_amount
from app.sim.state import PolicyPeriod

START = datetime(2026, 1, 1, tzinfo=UTC)
FOREVER = [PolicyPeriod("balanced", START - timedelta(days=1), None)]
NOW = START
BALANCED = FOREVER


def test_production_is_additive_and_integer_over_long_downtime():
    middle, end = START + timedelta(seconds=73), START + timedelta(days=900, seconds=5)
    assert production_amount(START, end, FOREVER, 2) == (900 * 86400 + 5) * 20
    assert (production_amount(START, middle, FOREVER, 2)
            + production_amount(middle, end, FOREVER, 2)
            == production_amount(START, end, FOREVER, 2))


def test_production_is_paid_at_the_rate_the_time_actually_had():
    """The rule the tick's boundary used to enforce, now enforced by arithmetic instead of by
    holding every city still. An hour at 10/s followed by an hour at 20/s is 108000, not
    either rate applied to the whole two hours."""
    switch = START + timedelta(hours=1)
    end = START + timedelta(hours=2)
    timeline = [
        PolicyPeriod("balanced", START, switch),
        PolicyPeriod("industrial", switch, None),
    ]
    assert production_amount(START, end, timeline, 0) == 3600 * 10 + 3600 * 20
    assert production_amount(START, end, timeline, 0) != production_amount(START, end, FOREVER, 0)


def test_a_gap_in_the_timeline_is_refused_rather_than_paid_as_nothing():
    """An uncovered stretch means the timeline is broken. Returning zero for it would turn a
    bug into quietly missing alloy that nobody could ever account for."""
    gapped = [
        PolicyPeriod("balanced", START, START + timedelta(hours=1)),
        PolicyPeriod("balanced", START + timedelta(hours=2), None),
    ]
    with pytest.raises(ValueError, match="does not cover"):
        production_amount(START, START + timedelta(hours=3), gapped, 0)


def test_policy_ties_preserve_incumbent():
    assert majority_policy("industrial", {}) == "industrial"
    assert majority_policy("balanced", {"balanced": 1, "industrial": 1}) == "balanced"
    assert majority_policy("balanced", {"industrial": 2}) == "industrial"


def test_invalid_time_cannot_mint_resources():
    with pytest.raises(ValueError):
        production_amount(START, START - timedelta(seconds=1), FOREVER, 0)
    with pytest.raises(ValueError):
        production_amount(START.replace(tzinfo=None), START, FOREVER, 0)
    with pytest.raises(ValueError):
        production_amount(START, START + timedelta(microseconds=1), FOREVER, 0)


def test_the_ground_pays_and_the_ground_charges():
    """Ruleset 2, and the reason for it: before this, where you landed changed the view and
    nothing else, so choosing a site was a formality with a scenery.

    The two knobs pull in opposite directions on purpose. One knob would only ever have made
    a ranking -- a best site, and a search instead of a decision.
    """
    # Rich ground pays more for the same level...
    poor = production_rate("balanced", 10, 1)
    rich = production_rate("balanced", 10, 88)
    assert rich > poor * 3 // 2

    # ... and takes far longer to reach the next one, because it has to be cleared first.
    open_ground = upgrade_duration(10, effort=0)
    overgrown = upgrade_duration(10, effort=48)
    assert overgrown > open_ground * 2

    # A site with nothing on it is the baseline, not a penalty: an unlanded colony produces
    # exactly what it produced before there was any ground in the rules at all.
    assert production_rate("balanced", 10, 0) == POLICY_RATES["balanced"] + 10 * LEVEL_RATE
    assert upgrade_duration(10) == UPGRADE_DURATION * 11


def test_the_ceiling_is_soft_because_landing_is_final():
    """A colony that runs out of ground gets slower and dearer, never finished. A wall would
    condemn whoever chose a delta, for ever, in a world where you cannot start again."""
    cramped = 600           # four levels' worth of buildable cells
    free = cramped // ROOM_PER_LEVEL
    assert free == 4

    # Inside its room, a cramped colony is an ordinary colony.
    assert upgrade_cost(0, cramped) == upgrade_cost(0)
    assert upgrade_duration(2, 0, cramped) == upgrade_duration(2)

    # Past it, both cost and time climb -- and keep climbing, rather than stopping.
    assert upgrade_cost(free, cramped) == upgrade_cost(free) * 2
    assert upgrade_cost(free + 3, cramped) == upgrade_cost(free + 3) * 5
    assert upgrade_duration(free + 3, 0, cramped) == upgrade_duration(free + 3) * 5
    # Dear, but never impossible.
    assert upgrade_cost(free + 50, cramped) < 10 ** 12


def test_a_stretched_upgrade_still_lands_on_a_whole_second():
    """The database refuses a sub-second timestamp, so a multiplier that introduced a
    fraction would fail at the INSERT -- long after the arithmetic that caused it."""
    for effort in range(0, 201, 7):
        for level in (0, 1, 9, 37):
            duration = upgrade_duration(level, effort, 10_000)
            assert duration.microseconds == 0, (level, effort)


def test_the_site_cannot_change_what_splitting_an_interval_means():
    """The whole reason production can accrue from timestamps: settling a week in one go and
    settling it a day at a time have to agree, to the milli."""
    start = NOW
    week = start + timedelta(days=7)
    for site_food in (0, 1, 37, 88, 100):
        whole = production_amount(start, week, BALANCED, 5, site_food)
        piecewise = sum(
            production_amount(start + timedelta(days=d), start + timedelta(days=d + 1),
                              BALANCED, 5, site_food)
            for d in range(7)
        )
        assert whole == piecewise, site_food
