import argparse
import json

from app.db import transaction
from app.service import provision
from app.worker import catch_up


def main():
    parser = argparse.ArgumentParser(description="Local administration; never exposed as HTTP")
    parser.add_argument("name", help="Name of the new player's city")
    args = parser.parse_args()
    catch_up()
    with transaction() as conn:
        result = provision(conn, args.name)
    print(json.dumps(result, default=str))  # Token shown once, only after commit.


if __name__ == "__main__":
    main()
