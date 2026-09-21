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

from app import db, gameclock, service
from app.db import database_now, transaction
from app.sim.config import harvest_rate
from app.service import balance, provision, start_upgrade


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
        start = service.stock(conn, player["city_id"])["stone"]
        opening = database_now(conn)

    with transaction() as conn:
        gameclock.set_speed(conn, 3600)
    import time
    time.sleep(1.1)

    with transaction() as conn:
        # The path a player actually takes: reading your own city settles it to the world's
        # now, which is what turns elapsed world time into stone.
        service.read_city(conn, player["city_id"], player["player_id"])
    with transaction() as conn:
        grown = service.stock(conn, player["city_id"])["stone"] - start
        elapsed_world = (database_now(conn) - opening).total_seconds()
    assert elapsed_world > 1800
    # La pietra si raccoglie al secondo di MONDO, non al secondo reale: e' questo
    # che rende l'orologio una manopola vera e non un'etichetta sopra lo stesso gioco.
    assert grown > harvest_rate("stone", 0, 0) * 1800


def test_a_compressed_world_lets_you_act_in_it(database):
    """The point of the exercise, end to end: commit to an upgrade, let the clock run, and it
    completes -- in seconds rather than an hour of world time.

    This used to have to fight the tick. It no longer does, and the thing it was fighting is
    worth recording: `require_current` refused every economic operation while a tick was
    overdue, and at 43200x the world was overdue almost always. A continuous world cannot be
    behind on anything, so a fast world is simply a fast world.
    """
    import time
    with transaction() as conn:
        player = provision(conn, "Cronos II")
    with transaction() as conn:
        gameclock.set_speed(conn, 86400)                    # a world day per real second
    with transaction() as conn:
        start_upgrade(conn, player["city_id"], player["player_id"], uuid4())

    deadline = time.monotonic() + 20
    level = 0
    while time.monotonic() < deadline and level == 0:
        time.sleep(0.1)
        with transaction() as conn:
            level = service.read_city(conn, player["city_id"], player["player_id"])["level"]
    assert level == 1, "an upgrade never completed in a compressed world"
