import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from app.gameclock import NOW_SQL


@contextmanager
def transaction():
    # A fresh connection avoids sharing transaction state between requests/workers.
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        conn.execute("SET LOCAL lock_timeout = '10s'")
        conn.execute("SET LOCAL statement_timeout = '60s'")
        yield conn


def database_now(conn):
    """Now, as the world reckons it -- not as the wall clock does.

    Every rule that spends or earns time reads this one function, which is what makes the
    world's clock a single knob instead of a search for `clock_timestamp()`. At the shipped
    speed of 1, with the anchors on one instant, this returns exactly what it always did: the
    formula in `gameclock.NOW_SQL` reduces to the real clock. See that module for why the
    speed lives on the world row and why changing it re-anchors.

    Audit columns (`recorded_at`, `completed_at`, `generated_at`) keep their real-time
    defaults on purpose: they say when a fact was WRITTEN, not when it holds in the world.
    """
    return conn.execute(
        f"SELECT date_trunc('second', {NOW_SQL}) AS now FROM world WHERE id = 1"
    ).fetchone()["now"]
