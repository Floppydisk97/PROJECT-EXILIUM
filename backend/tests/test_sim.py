"""The tick, exercised without a database.

These tests exist to prove the point of `app/sim/`: the rules of the game can be stated,
run and asserted on with nothing but values. No PostgreSQL, no schema, no fixtures, no
clock. If one of these fails, a rule is wrong -- not a query, not a lock, not a migration.
"""
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.sim import CityState, OrderState, WorldState, advance, snapshot
from app.sim.config import MAX_LEVEL, STARTING_ALLOY, TICK_INTERVAL, UPGRADE_COST

DUE = datetime(2026, 3, 1, tzinfo=UTC)
ONE = UUID("00000000-0000-0000-0000-000000000001")
TWO = UUID("00000000-0000-0000-0000-000000000002")


def world(policy="balanced", last_tick=0):
    return WorldState(policy=policy, last_tick=last_tick, next_tick_at=DUE)


def city(city_id=ONE, level=0, balance=STARTING_ALLOY, settled=DUE - timedelta(seconds=10)):
    return CityState(id=city_id, level=level, balance_milli=balance, settled_at=settled)


def test_production_is_paid_at_the_outgoing_rate_not_the_incoming_one():
    """The day belongs to the policy that was in force during it. Settling before resolving
    the election is the only reason this holds, so it is asserted directly."""
    result = advance(
        world(policy="balanced"),
        [city()],
        [OrderState(id=1, city_id=ONE, kind="policy_vote", choice="industrial")],
        DUE,
    )
    assert result.policy_after == "industrial"
    settlement = result.settlements[0]
    assert settlement.entry.amount == 10 * 10   # ten seconds at the balanced rate
    assert settlement.entry.effective_at == DUE


def test_an_upgrade_is_paid_out_of_production_settled_in_the_same_tick():
    poor = city(balance=UPGRADE_COST - 100, settled=DUE - timedelta(seconds=10))
    result = advance(
        world(), [poor], [OrderState(id=1, city_id=ONE, kind="upgrade", choice=None)], DUE
    )
    # 100 milli short before the tick, exactly covered by ten seconds of production.
    assert result.resolutions[0].outcome == "level_increased"
    assert result.resolutions[0].level_after == 1
    assert result.resolutions[0].entry.amount == -UPGRADE_COST


def test_an_unaffordable_upgrade_is_rejected_with_no_effects():
    result = advance(
        world(),
        [city(balance=0, settled=DUE)],
        [OrderState(id=1, city_id=ONE, kind="upgrade", choice=None)],
        DUE,
    )
    resolution = result.resolutions[0]
    assert (resolution.status, resolution.outcome) == ("rejected", "insufficient_alloy")
    assert resolution.entry is None and resolution.level_after is None
    assert result.rejected == 1 and result.applied == 0


def test_the_level_ceiling_is_enforced_by_the_rules_not_by_a_constraint():
    result = advance(
        world(),
        [city(level=MAX_LEVEL, settled=DUE)],
        [OrderState(id=1, city_id=ONE, kind="upgrade", choice=None)],
        DUE,
    )
    assert result.resolutions[0].outcome == "maximum_level"


def test_an_election_needs_a_majority_and_a_tie_keeps_the_incumbent():
    tie = advance(
        world(policy="balanced"),
        [city(ONE, settled=DUE), city(TWO, settled=DUE)],
        [
            OrderState(id=1, city_id=ONE, kind="policy_vote", choice="industrial"),
            OrderState(id=2, city_id=TWO, kind="policy_vote", choice="balanced"),
        ],
        DUE,
    )
    assert tie.votes == {"industrial": 1, "balanced": 1}
    assert tie.policy_after == "balanced"
    assert tie.applied == 2 and tie.rejected == 0

    silent = advance(world(policy="industrial"), [city(settled=DUE)], [], DUE)
    assert silent.policy_after == "industrial"


def test_the_boundary_advances_by_exactly_one_interval():
    result = advance(world(last_tick=7), [city(settled=DUE)], [], DUE)
    assert result.number == 8
    assert result.next_tick_at == DUE + TICK_INTERVAL


def test_a_city_already_at_the_boundary_settles_to_nothing():
    """No entry and no cursor move: re-running a tick must not manufacture production."""
    result = advance(world(), [city(settled=DUE)], [], DUE)
    assert result.settlements == ()
    assert result.cities_settled == 1   # counted as seen, not as moved


def test_the_same_inputs_always_produce_the_same_result():
    args = (
        world(),
        [city(ONE), city(TWO, level=3)],
        [
            OrderState(id=1, city_id=ONE, kind="upgrade", choice=None),
            OrderState(id=2, city_id=TWO, kind="policy_vote", choice="industrial"),
        ],
        DUE,
    )
    assert advance(*args) == advance(*args)


def test_the_state_is_serialisable_and_carries_its_ruleset():
    picture = snapshot(world(), [city(ONE), city(TWO, level=2)])
    assert picture["ruleset"] == 1
    assert json.loads(json.dumps(picture)) == picture   # no exotic types leaked in
    assert picture["cities"][1]["level"] == 2


def test_the_rules_never_touch_the_state_they_are_given():
    original = city()
    advance(world(), [original], [OrderState(1, ONE, "upgrade", None)], DUE)
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
                 "app.main", "app.mapservice", "app.worker"}

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
