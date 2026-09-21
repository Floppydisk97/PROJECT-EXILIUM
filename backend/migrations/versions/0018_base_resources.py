"""Risorse di base: il terreno dice COSA hai, non solo quanto vai forte."""
from pathlib import Path

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade():
    op.get_bind().exec_driver_sql(
        "ALTER TABLE cities DROP CONSTRAINT cities_site_needs_ground;"
        " ALTER TABLE cities DROP CONSTRAINT cities_site_complete;"
        " ALTER TABLE cities DROP COLUMN site_stone, DROP COLUMN site_timber;"
        " ALTER TABLE cities RENAME COLUMN site_food TO site_yield;"
        " ALTER TABLE cities ADD CONSTRAINT cities_site_all_or_nothing CHECK ("
        "  (site_yield IS NULL AND site_effort IS NULL AND site_room IS NULL)"
        "  OR (site_yield IS NOT NULL AND site_effort IS NOT NULL AND site_room IS NOT NULL));"
        " ALTER TABLE cities ADD CONSTRAINT cities_site_needs_ground CHECK ("
        "  site_yield IS NULL OR tile_id IS NOT NULL)"
    )
