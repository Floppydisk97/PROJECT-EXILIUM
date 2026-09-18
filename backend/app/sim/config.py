"""Balancing constants for ruleset 1. Data, not behaviour.

Every number the economy turns on lives here, so balancing is reading one file rather than
grepping for literals. `RULESET` stamps each resolved tick: a world records which rules
produced it, so a future change to these numbers is a new ruleset and not a silent rewrite
of history.
"""
from datetime import timedelta

RULESET = 1

# Production, in milli-alloy per second. Integers only: the economy must never depend on
# float rounding, since a saved world has to replay identically.
POLICY_RATES = {"balanced": 10, "industrial": 20}
LEVEL_RATE = 5          # each productive level adds this much per second
STARTING_ALLOY = 100_000
UPGRADE_COST = 100_000
MAX_LEVEL = 1_000_000

# Every tick closes at 00:00 UTC, exactly 24 hours apart, independent of restarts and of
# daylight saving. The persistent shared world is built on this boundary being wall-clock.
TICK_INTERVAL = timedelta(days=1)
