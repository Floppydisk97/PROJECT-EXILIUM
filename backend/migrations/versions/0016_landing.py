"""Landing: a colony takes a tile, and the tile decides the ground it gets."""
from pathlib import Path

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade():
    op.get_bind().exec_driver_sql(
        "DROP TRIGGER cities_landing_is_final ON cities;"
        " DROP FUNCTION reject_relanding;"
        " DROP INDEX cities_one_per_tile;"
        " ALTER TABLE cities"
        "  DROP CONSTRAINT cities_tile_exists,"
        "  DROP CONSTRAINT cities_landed_all_or_nothing,"
        "  DROP COLUMN map_seed, DROP COLUMN landed_at,"
        "  DROP COLUMN tile_id, DROP COLUMN map_id"
    )
