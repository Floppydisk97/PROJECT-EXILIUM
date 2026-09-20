from datetime import UTC, datetime, timedelta

import pytest

from app.sim.rules import majority_policy, production_amount
from app.sim.state import PolicyPeriod

START = datetime(2026, 1, 1, tzinfo=UTC)
FOREVER = [PolicyPeriod("balanced", START - timedelta(days=1), None)]


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
