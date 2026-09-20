"""The continuous world, exercised without a database.

These tests exist to prove the point of `app/sim/`: the rules of the game can be stated, run
and asserted on with nothing but values. No PostgreSQL, no schema, no fixtures, no clock. If
one of these fails, a rule is wrong -- not a query, not a lock, not a migration.

There is no tick to exercise any more. `advance_city` is what it became: the same question,
asked about one city instead of all of them.
"""
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.sim import CityState, Commitment, PolicyPeriod, advance_city, begin_upgrade, snapshot
from app.sim.config import (
    MAX_LEVEL, POLICY_RATES, STARTING_ALLOY, upgrade_cost, upgrade_duration,
)

NOW = datetime(2026, 3, 1, tzinfo=UTC)
ONE = UUID("00000000-0000-0000-0000-000000000001")
TWO = UUID("00000000-0000-0000-0000-000000000002")
BALANCED = [PolicyPeriod("balanced", NOW - timedelta(days=365), None)]


def city(city_id=ONE, level=0, balance=STARTING_ALLOY, settled=NOW - timedelta(seconds=10)):
    return CityState(id=city_id, level=level, balance_milli=balance, settled_at=settled)


def test_a_commitment_splits_the_interval_at_the_moment_it_completes():
    """The rule the tick's boundary used to enforce, and it does not stop being a rule just
    because the boundary is gone: production before the upgrade is earned at the OLD level,
    production after it at the new one. Settling the whole stretch and raising the level
    afterwards would pay the past at a rate the past did not have."""
    started = NOW - timedelta(seconds=10)
    done = NOW - timedelta(seconds=4)
    result = advance_city(
        city(settled=started), Commitment(1, ONE, "upgrade", done), BALANCED, NOW
    )
    before, after = result.settlements
    assert before.entry.amount == 6 * POLICY_RATES["balanced"]                  # level 0
    assert after.entry.amount == 4 * (POLICY_RATES["balanced"] + 5)             # level 1
    assert result.city.level == 1
    assert [c.outcome for c in result.completions] == ["level_increased"]


def test_a_commitment_not_yet_due_changes_nothing_but_the_cursor():
    later = Commitment(1, ONE, "upgrade", NOW + timedelta(hours=1))
    result = advance_city(city(), later, BALANCED, NOW)
    assert result.completions == ()
    assert result.city.level == 0
    assert result.city.settled_at == NOW


def test_a_city_already_at_now_settles_to_nothing():
    """No entry and no cursor move: re-reading a city must not manufacture production."""
    result = advance_city(city(settled=NOW), None, BALANCED, NOW)
    assert result.settlements == () and result.completions == ()
    assert result.city == city(settled=NOW)


def test_committing_spends_immediately_and_buys_a_moment():
    decision = begin_upgrade(city(settled=NOW), busy=False, now=NOW)
    spend, completes_at = decision
    assert spend.amount == -upgrade_cost(0)
    assert spend.effective_at == NOW
    assert completes_at == NOW + upgrade_duration(0)


def test_a_busy_city_cannot_start_a_second_thing():
    """The whole of the new scarcity, in one assertion. There is no queue to be limited: the
    limit is that a city does one thing at a time, so starting something is choosing not to
    start anything else until it finishes."""
    assert begin_upgrade(city(settled=NOW), busy=True, now=NOW) == "already_busy"


def test_an_unaffordable_upgrade_is_refused_with_no_effects():
    assert begin_upgrade(city(balance=0, settled=NOW), False, NOW) == "insufficient_alloy"


def test_the_cost_and_the_wait_both_grow_with_the_level():
    """A flat cost against compounding production measured out as a pure exponential with
    nothing to decide. Both curves rise so that time, not alloy, is what a level costs."""
    assert upgrade_cost(9) == 10 * upgrade_cost(0)
    assert upgrade_duration(9) == 10 * upgrade_duration(0)


def test_the_level_ceiling_is_enforced_by_the_rules_not_by_a_constraint():
    assert begin_upgrade(city(level=MAX_LEVEL, settled=NOW), False, NOW) == "maximum_level"


def test_the_same_inputs_always_produce_the_same_result():
    args = (city(), Commitment(1, ONE, "upgrade", NOW - timedelta(seconds=5)), BALANCED, NOW)
    assert advance_city(*args) == advance_city(*args)


def test_the_state_is_serialisable_and_carries_its_ruleset():
    picture = snapshot("balanced", [city(ONE), city(TWO, level=2)])
    assert picture["ruleset"] == 1
    assert json.loads(json.dumps(picture)) == picture   # no exotic types leaked in
    assert picture["cities"][1]["level"] == 2


def test_the_rules_never_touch_the_state_they_are_given():
    original = city()
    advance_city(original, Commitment(1, ONE, "upgrade", NOW), BALANCED, NOW)
    assert original == city()   # frozen in, frozen out: effects are described, not applied


def test_the_simulation_core_imports_nothing_that_knows_about_storage_or_transport():
    """The boundary is the whole value of this module, and a convention only holds until
    someone is in a hurry. This is the convention made mechanical: `app/sim/` may not learn
    about PostgreSQL, HTTP, or the adapter that uses it.

    Parsed rather than grepped -- a docstring that merely *names* psycopg is prose, not a
    dependency, and a guard that cannot tell the difference would be one more thing to work
    around instead of a rule.
    """
    import ast
    from pathlib import Path

    forbidden = {"psycopg", "fastapi", "alembic", "starlette", "app.db", "app.service",
                 "app.main", "app.mapservice", "app.worker", "app.gameclock"}

    def offends(module: str | None) -> bool:
        if not module:
            return False
        return any(module == name or module.startswith(name + ".") for name in forbidden)

    modules = sorted((Path(__file__).parents[1] / "app" / "sim").glob("*.py"))
    assert len(modules) >= 4   # guard against the glob silently matching nothing
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not offends(alias.name), f"{path.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert not offends(node.module), f"{path.name} imports from {node.module}"
