"""Balancing constants for ruleset 2. Data, not behaviour.

Every number the economy turns on lives here, so balancing is reading one file rather than
grepping for literals. `RULESET` stamps every ledger row: a world records which rules
produced it, so a future change to these numbers is a new ruleset and not a silent rewrite
of history. It used to be stamped on the tick; with no tick, each movement carries it.
"""
from datetime import timedelta

RULESET = 2

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


# What the ground is worth. Ruleset 2: before it, where you landed changed the view and
# nothing else, so choosing a site was a formality with a scenery.
#
# Three numbers, measured on the colony's own map at landing (see `citygen.SiteEconomy`), and
# deliberately pulling in different directions -- because one number would only ever produce a
# ranking, and a ranking is not a decision. Rich ground pays more per level and takes far
# longer to reach the next; open poor ground pays almost nothing per level and accumulates
# them without end. Simulated over a year of world time, the fertile site leads by 37 per cent
# at ten days and the desert has passed it by the end: neither is the answer, which is the
# point.
YIELD_BASE = 150        # rate is multiplied by (YIELD_BASE + yield) / YIELD_BASE: 1.00 .. 1.67
EFFORT_WEIGHT = 4       # an upgrade lasts (100 + EFFORT_WEIGHT * effort) / 100 as long
ROOM_PER_LEVEL = 150    # buildable cells a level takes before the colony starts to crowd


def production_rate(policy: str, level: int, site_food: int = 0) -> int:
    """Milli-alloy per second. One integer for the whole slice it is used over.

    The rounding happens HERE, once, and not per second: the rate has to be the same integer
    however an interval is split, or settling a week in one go would differ from settling it
    in seven days -- and production accruing from timestamps depends on those being equal.
    """
    return ((POLICY_RATES[policy] + level * LEVEL_RATE) * (YIELD_BASE + site_food)) // YIELD_BASE


def crowding(level: int, room: int | None) -> int:
    """How far past its room the colony is reaching. Zero while there is space.

    A soft ceiling, not a wall: landing is irreversible, so a colony that ran out of ground
    must get slower and dearer, never finished. `room=None` is a colony with no ground yet --
    it has not landed -- and it is not crowded by nothing.
    """
    if room is None:
        return 0
    return max(0, level + 1 - room // ROOM_PER_LEVEL)


def upgrade_cost(level: int, room: int | None = None) -> int:
    """Milli-alloy to commit to the upgrade that leaves `level` behind."""
    return UPGRADE_COST * (level + 1) * (1 + crowding(level, room))


def upgrade_duration(level: int, effort: int = 0, room: int | None = None) -> timedelta:
    """World time that upgrade occupies the city for.

    Whole seconds always, which the database requires: the hour is divisible by a hundred, so
    the effort multiplier can never introduce a fraction of a second.
    """
    stretched = UPGRADE_DURATION * (level + 1) * (100 + EFFORT_WEIGHT * effort) // 100
    return stretched * (1 + crowding(level, room))
