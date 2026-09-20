"""The world's clock, and the property that makes it safe to ship.

A tick a day makes the game impossible to playtest. Compressing it means compressing the
clock the simulation reads -- not the tick's cadence, because production is a rate per second
worked out from timestamps and a shorter tick would only buy more ceremonies with less in
each. These tests hold the arithmetic, and above all they hold the promise that at the
shipped speed of 1 nothing whatsoever is different.
"""
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest

from app import gameclock, service, worker
from app.db import database_now, transaction
from app.service import balance, provision, run_tick


def test_at_speed_one_the_world_clock_is_the_real_clock(database):
    """The whole reason this can be shipped into a world meant to run at one second per
    second. Not "close to": the anchors sit on one instant, so the subtraction and the
    addition cancel and the formula reduces to the wall clock."""
    with transaction() as conn:
        clock = gameclock.read_clock(conn)
    assert clock["speed"] == 1.0
    assert clock["anchor_real"] == clock["anchor_world"]
    assert abs((clock["world_now"] - clock["real_now"]).total_seconds()) < 1


def test_a_faster_world_runs_faster(database):
    with transaction() as conn:
        gameclock.set_speed(conn, 3600)
    with transaction() as conn:
        first = database_now(conn)
    import time
    time.sleep(1.1)
    with transaction() as conn:
        second = database_now(conn)
    # An hour of world time per real second: a real second must buy far more than a second.
    elapsed = (second - first).total_seconds()
    assert elapsed > 1800, f"world advanced only {elapsed}s in a real second"


def test_changing_the_speed_does_not_move_the_world(database):
    """The re-anchoring. Changing `time_speed` alone would throw the world forward or back by
    days, and backwards means a negative production interval and a ledger that does not add
    up. The new anchor is computed from the OLD speed, so the two formulas meet at the moment
    of the change."""
    with transaction() as conn:
        before = database_now(conn)
        gameclock.set_speed(conn, 1000)
        after = database_now(conn)
    assert timedelta(0) <= after - before < timedelta(seconds=2)


def test_the_world_clock_never_goes_backwards(database):
    """Monotonicity is not decoration: `settle_city` computes production over an interval, and
    an interval that runs backwards mints negative alloy."""
    readings = []
    for speed in (60, 5, 3600, 1, 900):
        with transaction() as conn:
            gameclock.set_speed(conn, speed)
            readings.append(database_now(conn))
    assert readings == sorted(readings)


def test_a_speed_of_zero_or_less_is_refused(database):
    with transaction() as conn:
        with pytest.raises(ValueError):
            gameclock.set_speed(conn, 0)
    # ... and the database refuses it too, so no other path can get round the check.
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute("UPDATE world SET time_speed = -1 WHERE id = 1")


def test_production_scales_with_the_clock(database):
    """The point of the whole exercise, measured rather than assumed: the same real second
    must be worth more alloy in a faster world."""
    with transaction() as conn:
        player = provision(conn, "Cronos")
    with transaction() as conn:
        start = balance(conn, player["city_id"])
        opening = database_now(conn)

    with transaction() as conn:
        gameclock.set_speed(conn, 3600)
    import time
    time.sleep(1.1)

    with transaction() as conn:
        # The path a player actually takes: reading your own city settles it to the world's
        # now, which is what turns elapsed world time into alloy.
        service.read_city(conn, player["city_id"], player["player_id"])
    with transaction() as conn:
        grown = balance(conn, player["city_id"]) - start
        elapsed_world = (database_now(conn) - opening).total_seconds()
    assert elapsed_world > 1800
    # balanced = 10 milli-alloy per world second, level 0.
    assert grown > 10 * 1800


def test_the_worker_breathes_at_the_world_speed(database):
    """Found by playing, not by reading.

    The worker slept a fixed five seconds between rounds. At one day per day the window
    between midnight and the worker noticing is a blink and nobody ever meets it. At 43200x a
    world day goes by in two seconds, so that same nap leaves the world overdue almost always
    -- and `require_current` refuses every economic operation while it is. A compressed world
    was unplayable for exactly that reason: submitting an order answered 503.
    """
    with transaction() as conn:
        assert worker.idle_wait(conn) == worker.IDLE_MAX          # speed 1: as it always was

    with transaction() as conn:
        gameclock.set_speed(conn, 43200)
        fast = worker.idle_wait(conn)
    assert fast == pytest.approx(0.5)      # four looks per world day

    with transaction() as conn:
        gameclock.set_speed(conn, 10_000_000)
        assert worker.idle_wait(conn) == worker.IDLE_MIN          # ... but never a tight spin


def test_a_compressed_world_lets_you_act_in_it(database):
    """The point of the exercise, end to end: submit, let the clock run, and the order
    resolves -- in seconds rather than a day. This is the test that would have caught the
    worker's fixed nap, because it fails with a 503 instead of an assertion."""
    import time
    with transaction() as conn:
        player = provision(conn, "Cronos II")
    with transaction() as conn:
        gameclock.set_speed(conn, 86400)                          # a world day per second

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with transaction() as conn:
            run_tick(conn)
        with transaction() as conn:
            try:
                city = service.read_city(conn, player["city_id"], player["player_id"])
            except service.DomainError:
                continue                                          # a tick is due; go round again
        if city["level"] == 0 and not _has_pending(player):
            with transaction() as conn:
                service.submit_order(conn, player["city_id"], player["player_id"],
                                     uuid4(), "upgrade", None)
        if city["level"] > 0:
            break
        time.sleep(0.05)
    assert city["level"] > 0, "a compressed world never resolved an order"


def _has_pending(player) -> bool:
    with transaction() as conn:
        return conn.execute(
            "SELECT 1 FROM orders WHERE city_id = %s AND status = 'pending'",
            (player["city_id"],),
        ).fetchone() is not None
