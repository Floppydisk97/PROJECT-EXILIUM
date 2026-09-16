import os

from alembic import context
from sqlalchemy import create_engine, pool

url = os.environ["DATABASE_URL"]
engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1), poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        # Also serialize concurrent deployment migration jobs.
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(7392401)")
        context.run_migrations()
