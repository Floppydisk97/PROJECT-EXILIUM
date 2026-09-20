"""Balancing constants for ruleset 1. Data, not behaviour.

Every number the economy turns on lives here, so balancing is reading one file rather than
grepping for literals. `RULESET` stamps every ledger row: a world records which rules
produced it, so a future change to these numbers is a new ruleset and not a silent rewrite
of history. It used to be stamped on the tick; with no tick, each movement carries it.
"""
from datetime import timedelta

RULESET = 1

# Production, in milli-alloy per second. Integers only: the economy must never depend on
# float rounding, since a saved world has to replay identically.
POLICY_RATES = {"balanced": 10, "industrial": 20}
LEVEL_RATE = 5          # each productive level adds this much per second
STARTING_ALLOY = 100_000
MAX_LEVEL = 1_000_000

# An upgrade costs alloy AND time, and both grow with the level being left behind.
#
# Time is the one that matters. With production compounding (every level adds LEVEL_RATE per
# second) and a flat cost, the game measured out as a pure exponential with nothing to decide:
# the only strategy was to spend the moment you could afford it. What a continuous world has
# instead of a queue is scarcity of ATTENTION -- a city does one thing at a time, so choosing
# to start something is choosing not to start anything else until it finishes.
#
# Starting numbers, not balanced ones. At level 0 an upgrade is an hour of world time and 100
# alloy; at level 10 it is eleven hours and 1100. Turn them here.
UPGRADE_COST = 100_000
UPGRADE_DURATION = timedelta(hours=1)


def upgrade_cost(level: int) -> int:
    """Milli-alloy to commit to the upgrade that leaves `level` behind."""
    return UPGRADE_COST * (level + 1)


def upgrade_duration(level: int) -> timedelta:
    """World time that upgrade occupies the city for."""
    return UPGRADE_DURATION * (level + 1)
