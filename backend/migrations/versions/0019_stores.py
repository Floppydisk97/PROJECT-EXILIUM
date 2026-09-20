"""Il magazzino: da una risorsa a quattro, da una colonna a una tabella."""
from pathlib import Path

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


# Il trigger che c'era prima. Una downgrade che lascia in piedi la versione nuova
# lascerebbe il database senza controllo di scoperto, che e' peggio di non tornare indietro.
OLD_TRIGGER = """
CREATE OR REPLACE FUNCTION validate_ledger_entry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    city_created timestamptz;
    current_balance bigint;
BEGIN
    SELECT created_at, balance_milli INTO city_created, current_balance
        FROM cities WHERE id = NEW.city_id FOR UPDATE;
    IF NEW.effective_at < city_created THEN
        RAISE EXCEPTION 'ledger entry precedes city' USING ERRCODE = '23514';
    END IF;
    IF current_balance + NEW.amount < 0 THEN
        RAISE EXCEPTION 'insufficient balance' USING ERRCODE = '23514';
    END IF;
    UPDATE cities SET balance_milli = current_balance + NEW.amount WHERE id = NEW.city_id;
    RETURN NEW;
END;
$$;
"""


def downgrade():
    op.get_bind().exec_driver_sql(
        "ALTER TABLE cities ADD COLUMN balance_milli bigint NOT NULL DEFAULT 0"
        "  CHECK (balance_milli >= 0);"
        " UPDATE cities c SET balance_milli = COALESCE("
        "  (SELECT amount_milli FROM city_stock WHERE city_id = c.id AND resource = 'alloy'), 0);"
        " DROP TABLE city_stock;"
        " ALTER TABLE resource_ledger DROP CONSTRAINT resource_ledger_resource_check;"
        " ALTER TABLE resource_ledger ADD CONSTRAINT resource_ledger_resource_check"
        "  CHECK (resource = 'alloy');" + OLD_TRIGGER
    )
