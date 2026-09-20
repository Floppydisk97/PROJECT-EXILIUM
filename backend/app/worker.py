import argparse
import logging
import signal
import threading

from app.db import transaction
from app.service import run_tick
from app.sim.config import TICK_INTERVAL

logger = logging.getLogger("exilium.tick")

# How often to look, as a fraction of a world day. Four looks per day keeps the window in
# which the world is overdue short compared with the day itself.
LOOKS_PER_DAY = 4
IDLE_MIN, IDLE_MAX = 0.05, 5.0


def idle_wait(conn) -> float:
    """How long to sleep when there was nothing to do, sized to the world's own clock.

    A fixed five seconds is right for a world where a day lasts a day: the window between
    midnight and the worker noticing is a blink, and nobody meets it. Under a compressed clock
    it is the opposite -- at 43200x a world day passes in two seconds, so a five-second nap
    leaves the world overdue almost always, and `require_current` then refuses every economic
    operation. Found by playing a compressed world rather than by reading the code.

    At speed 1 this returns IDLE_MAX, which is exactly what it always did.
    """
    speed = float(conn.execute("SELECT time_speed FROM world WHERE id = 1").fetchone()["time_speed"])
    return min(IDLE_MAX, max(IDLE_MIN, TICK_INTERVAL.total_seconds() / speed / LOOKS_PER_DAY))


def catch_up(limit=32):
    count = 0
    for _ in range(limit):
        with transaction() as conn:
            result = run_tick(conn)
        if result is None:
            break
        count += 1
        logger.info("tick_committed number=%s due_at=%s", result["number"], result["due_at"])
    return count


def _idle_wait() -> float:
    try:
        with transaction() as conn:
            return idle_wait(conn)
    except Exception:                                   # noqa: BLE001
        # A database that will not answer is already being retried by the loop; falling back
        # to the slow cadence is better than a tight spin against a failing connection.
        return IDLE_MAX


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Recover up to 32 ticks and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.once:
        catch_up()
        return
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            count = catch_up()
        except Exception:
            logger.exception("tick_failed; transaction rolled back, retrying")
            count = 0
        stop.wait(0.1 if count == 32 else _idle_wait())


if __name__ == "__main__":
    main()
