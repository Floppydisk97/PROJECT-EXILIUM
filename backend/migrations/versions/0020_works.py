"""Opere e filoni: la produzione smette di essere una moltiplicazione."""
from pathlib import Path

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade():
    op.get_bind().exec_driver_sql(
        "DROP TABLE city_works;"
        " ALTER TABLE resource_ledger DROP CONSTRAINT resource_ledger_check;"
        " ALTER TABLE resource_ledger ADD CONSTRAINT resource_ledger_check CHECK ("
        "  (reason IN ('genesis', 'production') AND amount > 0)"
        "  OR (reason = 'upgrade' AND amount < 0));"
        " ALTER TABLE resource_ledger DROP CONSTRAINT resource_ledger_resource_check;"
        " ALTER TABLE resource_ledger ADD CONSTRAINT resource_ledger_resource_check"
        "  CHECK (resource IN ('alloy', 'food', 'timber', 'stone'));"
        " ALTER TABLE orders DROP CONSTRAINT orders_kind_check;"
        " ALTER TABLE orders ADD CONSTRAINT orders_kind_check"
        "  CHECK (kind IN ('upgrade', 'policy_vote'));"
        " ALTER TABLE orders DROP CONSTRAINT orders_check;"
        " ALTER TABLE orders ADD CONSTRAINT orders_check CHECK ("
        "  (kind = 'upgrade' AND choice IS NULL)"
        "  OR (kind = 'policy_vote' AND choice IN ('balanced', 'industrial')));"
        " ALTER TABLE cities DROP CONSTRAINT cities_site_complete;"
        " ALTER TABLE cities DROP COLUMN site_ore;"
        " ALTER TABLE cities ADD CONSTRAINT cities_site_complete CHECK ("
        "  (site_food IS NULL AND site_timber IS NULL AND site_stone IS NULL"
        "   AND site_effort IS NULL AND site_room IS NULL)"
        "  OR (site_food IS NOT NULL AND site_timber IS NOT NULL AND site_stone IS NOT NULL"
        "      AND site_effort IS NOT NULL AND site_room IS NOT NULL))"
    )
