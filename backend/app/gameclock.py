"""The clock the simulation reads.

A tick a day makes the game impossible to playtest: a move is judged twenty-four hours
later. The fix is not a shorter tick. Production is not made by the tick -- `POLICY_RATES` is
milli-alloy per SECOND and `settle_city` works it out from the difference between two
timestamps, while the tick only walks the cursor up to the boundary. Cutting TICK_INTERVAL
from a day to ten seconds would buy 8640 ceremonies a day with a ten-thousandth of the
substance each, and the game would run at exactly the same speed.

What has to be compressed is the clock, not the cadence:

    world_time = anchor_world + (real_time - anchor_real) * speed

Two anchors rather than one, because changing the speed has to keep world time CONTINUOUS.
Changing `speed` alone would jump the world forward or back by days -- and backwards means a
negative production interval and a ledger that does not add up. So a change of speed first
moves the anchor to the current instant, after which continuity holds by construction: at the
moment of the change both formulas give the same value.

And with both anchors on the same instant and speed 1 the formula reduces to `real_time`
exactly -- not nearly: the subtraction and the addition cancel. So this machinery is inert
until somebody turns the knob, which is what makes it safe to ship into a world that is
supposed to run at one second per second.
"""
import argparse
import json

# One definition of the mapping, in SQL, used both to read the clock and to re-anchor it.
# Written once because two copies of an arithmetic rule that must agree is how this project
# has been bitten before.
NOW_SQL = "time_anchor_world + (clock_timestamp() - time_anchor_real) * time_speed"


def read_clock(conn) -> dict:
    """The clock's parameters and what it currently reads."""
    return dict(conn.execute(
        f"""SELECT time_speed AS speed, time_anchor_real AS anchor_real,
                   time_anchor_world AS anchor_world,
                   date_trunc('second', {NOW_SQL}) AS world_now,
                   date_trunc('second', clock_timestamp()) AS real_now
            FROM world WHERE id = 1"""
    ).fetchone())


def set_speed(conn, speed: float) -> dict:
    """Re-anchor on the current instant, then change the speed. Order matters and is the
    whole point: the new anchor is computed from the OLD speed, which is what makes the two
    formulas meet at the moment of the change instead of the world jumping."""
    if speed <= 0:
        raise ValueError("Speed must be greater than zero")
    # A single clock_timestamp(), used for both the new anchor and the elapsed term: calling
    # it twice would leave a microsecond of drift, which at a speed of 3600 is milliseconds
    # of world time appearing out of nothing.
    conn.execute(
        f"""UPDATE world SET
                time_anchor_world = {NOW_SQL.replace("clock_timestamp()", "t.real_now")},
                time_anchor_real = t.real_now,
                time_speed = %s
            FROM (SELECT clock_timestamp() AS real_now) t
            WHERE world.id = 1""",
        (speed,),
    )
    return read_clock(conn)


def city_count(conn) -> int:
    return int(conn.execute("SELECT count(*) AS n FROM cities").fetchone()["n"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read or set the world's clock speed. Development tool: a shared world "
                    "is supposed to run at one second per second.",
    )
    parser.add_argument("speed", nargs="?", type=float,
                        help="World seconds per real second. Omit to just read the clock.")
    parser.add_argument("--yes", action="store_true",
                        help="Required to change the speed of a world that has cities in it.")
    args = parser.parse_args()

    from app.db import transaction
    with transaction() as conn:
        if args.speed is None:
            print(json.dumps(read_clock(conn), indent=2, default=str))
            return
        # Changing the speed under a world with players in it moves every city's production
        # rate per real second. Harmless while the cities are ours; not something to do by
        # accident once they are not.
        settled = city_count(conn)
        if settled and not args.yes:
            raise SystemExit(
                f"This world has {settled} cities; changing the clock changes what every one "
                f"of them earns per real second. Pass --yes if that is what you mean."
            )
        print(json.dumps(set_speed(conn, args.speed), indent=2, default=str))


if __name__ == "__main__":
    main()
