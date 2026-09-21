"""Il terreno entra nell'economia: resa, fatica e spazio sulla riga della citta'."""
from pathlib import Path

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade():
    op.get_bind().exec_driver_sql(
        "ALTER TABLE cities"
        "  DROP CONSTRAINT cities_site_needs_ground,"
        "  DROP CONSTRAINT cities_site_all_or_nothing,"
        "  DROP COLUMN site_room, DROP COLUMN site_effort, DROP COLUMN site_yield"
    )
