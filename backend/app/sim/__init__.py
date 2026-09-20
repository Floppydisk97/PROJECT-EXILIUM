"""The simulation core: rules and state, with no I/O of any kind.

Nothing under `app/sim/` may import psycopg, FastAPI or anything else that knows about
storage or transport. That single constraint is the module's reason to exist -- it is what
keeps the rules of the game readable on their own, testable without a database, and portable
to another engine later.

There is no tick here any more. The world is continuous: production accrues per second,
commitments complete at the moment they are due, and policy is a timeline. `advance_city` is
what the tick used to be, except about one city instead of all of them -- which is what
removed the global barrier.
"""
from app.sim.rules import advance_city, begin_upgrade, majority_policy, settle_city
from app.sim.state import (
    Advance, CityState, Commitment, Completion, LedgerEntry, PolicyPeriod, Settlement,
    snapshot,
)

__all__ = [
    "Advance", "CityState", "Commitment", "Completion", "LedgerEntry", "PolicyPeriod",
    "Settlement", "advance_city", "begin_upgrade", "majority_policy", "settle_city",
    "snapshot",
]
