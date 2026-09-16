from datetime import UTC, datetime, timedelta

import pytest

from app.domain import elected_policy, production_amount, production_rate


def test_production_is_additive_and_integer_over_long_downtime():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    middle, end = start + timedelta(seconds=73), start + timedelta(days=900, seconds=5)
    assert production_amount(start, end, "balanced", 2) == (900 * 86400 + 5) * 20
    assert production_amount(start, middle, "balanced", 2) + production_amount(middle, end, "balanced", 2) == production_amount(start, end, "balanced", 2)


def test_policy_ties_preserve_incumbent():
    assert elected_policy("industrial", {}) == "industrial"
    assert elected_policy("balanced", {"balanced": 1, "industrial": 1}) == "balanced"
    assert elected_policy("balanced", {"industrial": 2}) == "industrial"


def test_extractor_adds_to_existing_production_rules():
    assert production_rate("balanced", 2, 0) == 20
    assert production_rate("balanced", 2, 1) == 45


def test_invalid_time_cannot_mint_resources():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        production_amount(start, start - timedelta(seconds=1), "balanced", 0)
    with pytest.raises(ValueError):
        production_amount(start.replace(tzinfo=None), start, "balanced", 0)
    with pytest.raises(ValueError):
        production_amount(start, start + timedelta(microseconds=1), "balanced", 0)
