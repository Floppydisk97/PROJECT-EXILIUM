from datetime import datetime

RULESET = 1
UPGRADE_COST = 100_000
STARTING_ALLOY = 100_000
EXTRACTOR_COST = 60_000
EXTRACTOR_RATE = 25
MAX_LEVEL = 1_000_000
POLICY_RATES = {"balanced": 10, "industrial": 20}


def production_rate(policy: str, level: int, extractors: int = 0) -> int:
    if level < 0 or extractors < 0:
        raise ValueError("Invalid production inputs")
    return POLICY_RATES[policy] + level * 5 + extractors * EXTRACTOR_RATE


def production_amount(start: datetime, end: datetime, policy: str, level: int, extractors: int = 0) -> int:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Timezone-aware timestamps required")
    if start.microsecond or end.microsecond:
        raise ValueError("Production timestamps must have whole-second precision")
    if end < start:
        raise ValueError("Invalid production interval or level")
    elapsed = end - start
    seconds = elapsed.days * 86400 + elapsed.seconds
    return seconds * production_rate(policy, level, extractors)


def elected_policy(current: str, votes: dict[str, int]) -> str:
    balanced = votes.get("balanced", 0)
    industrial = votes.get("industrial", 0)
    if balanced == industrial:
        return current
    return "balanced" if balanced > industrial else "industrial"
