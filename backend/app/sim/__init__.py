"""The simulation core: rules, state and the tick, with no I/O of any kind.

Nothing under `app/sim/` may import psycopg, FastAPI or anything else that knows about
storage or transport. That single constraint is the module's reason to exist -- it is what
keeps the rules of the game readable on their own, testable without a database, and
portable to another engine later.
"""
from app.sim.state import (
    CityState, LedgerEntry, OrderResolution, OrderState, Settlement, TickResult, WorldState,
    snapshot,
)
from app.sim.tick import advance

__all__ = [
    "CityState", "LedgerEntry", "OrderResolution", "OrderState", "Settlement", "TickResult",
    "WorldState", "advance", "snapshot",
]
