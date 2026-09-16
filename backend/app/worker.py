import argparse
import logging
import signal
import threading

from app.db import transaction
from app.service import run_tick

logger = logging.getLogger("exilium.tick")


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
        stop.wait(0.1 if count == 32 else 5)


if __name__ == "__main__":
    main()
