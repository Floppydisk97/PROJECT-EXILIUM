import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from app.main import _rate


@pytest.fixture
def database(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL integration tests")
    # A fresh schema per test: never truncate or drop existing application data.
    schema = "test_exilium_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    # Un contatore di richieste vivo nel processo porterebbe le chiamate di una prova
    # dentro la successiva.
    _rate.clear()
    try:
        command.upgrade(config, "head")
        yield config
    finally:
        _rate.clear()
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
