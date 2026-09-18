"""The tick: the one rule that is about the whole world at once.

`advance` is a pure function. It reads a world, its cities and the orders aimed at this
tick, and returns everything that should happen -- ledger movements, settled cursors, order
outcomes, the elected policy and the next boundary -- without touching a database. The
caller applies the result in a single transaction and is free to throw it away instead.

That is what makes the tick testable without PostgreSQL, replayable from a snapshot, and
comparable between versions: given the same inputs it returns the same result, every time.
"""
from __future__ import annotations

from datetime import datetime

from app.sim.config import TICK_INTERVAL
from app.sim.rules import elected_policy, resolve_order, settle_city
from app.sim.state import CityState, OrderState, Settlement, TickResult, WorldState


def advance(
    world: WorldState,
    cities: list[CityState],
    orders: list[OrderState],
    due: datetime,
) -> TickResult:
    """Resolve the tick that closes at `due`.

    Order matters and is part of the rules. Every city is settled to the boundary *first*,
    at the outgoing policy and the outgoing level, so a day's production is never paid at a
    rate the day did not have. Only then are orders resolved, in id order, against balances
    that already include that production. The election applies to the period that follows.
    """
    number = world.last_tick + 1
    settlements: list[Settlement] = []
    current: dict = {}

    for city in cities:
        settlement = settle_city(city, due, world.policy)
        if settlement is not None:
            settlements.append(settlement)
            city = settlement.city
        current[city.id] = city

    votes: dict[str, int] = {}
    resolutions = []
    applied = rejected = 0
    for order in orders:
        resolution, updated = resolve_order(order, current[order.city_id], due)
        current[order.city_id] = updated
        if order.kind == "policy_vote" and order.choice is not None:
            votes[order.choice] = votes.get(order.choice, 0) + 1
        resolutions.append(resolution)
        applied += resolution.status == "applied"
        rejected += resolution.status == "rejected"

    return TickResult(
        number=number,
        due_at=due,
        next_tick_at=due + TICK_INTERVAL,
        policy_before=world.policy,
        policy_after=elected_policy(world.policy, votes),
        cities_settled=len(cities),
        settlements=tuple(settlements),
        resolutions=tuple(resolutions),
        votes=votes,
        applied=applied,
        rejected=rejected,
    )
