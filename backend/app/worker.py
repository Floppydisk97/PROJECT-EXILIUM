"""The sweeper.

It used to be the tick: the one process that moved the whole world forward, holding every
city still while it did. That job is gone. Production accrues from timestamps and commitments
complete the moment somebody reads the city, so a world nobody is looking at is already
correct -- it simply has not been written down yet.

What is left is worth doing anyway. A city whose upgrade finished should stop saying it is
busy even while its owner is asleep, and other players looking at a shared world should see
what it really is rather than what it was. So this walks the cities that have something due
and advances them, ONE AT A TIME, under a lock on that city alone. Two cities never wait for
each other, and nothing waits for all of them.
"""
import argparse
import logging
import signal
import threading

from app import db
from app.db import transaction
from app.service import advance

logger = logging.getLogger("exilium.sweep")

# Nothing is ever urgent here -- a city is correct when read whether or not this ran. The
# sweep exists so the written-down world does not drift far behind the real one.
IDLE = 5.0
BATCH = 64


def due_cities(conn, limit=BATCH):
    """Cities holding a commitment that has come due, oldest first."""
    return conn.execute(
        """SELECT c.* FROM cities c
           JOIN orders o ON o.city_id = c.id AND o.status = 'pending'
           WHERE o.completes_at <= %s
           ORDER BY o.completes_at
           LIMIT %s""",
        (db.database_now(conn), limit),
    ).fetchall()


def sweep(limit=BATCH):
    """Advance every city with something due. One transaction per city on purpose: a failure
    on one must not roll back the others, and a long batch must not hold a lock on the first
    city while it works on the last."""
    with transaction() as conn:
        pending = [row["id"] for row in due_cities(conn, limit)]
    swept = 0
    for city_id in pending:
        with transaction() as conn:
            row = conn.execute(
                "SELECT * FROM cities WHERE id = %s FOR UPDATE", (city_id,)
            ).fetchone()
            if row is None:
                continue
            result = advance(conn, row, db.database_now(conn))
        if result.completions:
            swept += 1
            logger.info("completed city=%s level=%s", city_id, result.city.level)
    return swept


def catch_up(limit=BATCH):
    """Kept under its old name because the CLI and the tests ask for it by it."""
    return sweep(limit)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Sweep once and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.once:
        sweep()
        return
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            count = sweep()
        except Exception:
            logger.exception("sweep_failed; transaction rolled back, retrying")
            count = 0
        # A full batch means there is more waiting, so come straight back for it.
        stop.wait(0.1 if count >= BATCH else IDLE)


if __name__ == "__main__":
    main()
