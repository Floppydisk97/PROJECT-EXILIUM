import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


@contextmanager
def transaction():
    # A fresh connection avoids sharing transaction state between requests/workers.
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        conn.execute("SET LOCAL lock_timeout = '10s'")
        conn.execute("SET LOCAL statement_timeout = '60s'")
        yield conn


def database_now(conn):
    return conn.execute("SELECT date_trunc('second', clock_timestamp()) AS now").fetchone()["now"]
