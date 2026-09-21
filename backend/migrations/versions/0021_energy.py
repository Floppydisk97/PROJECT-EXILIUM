"""L'energia come flusso, le quattro attitudini del luogo, e la pausa."""
from pathlib import Path

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade():
    op.get_bind().exec_driver_sql(
        "ALTER TABLE orders DROP CONSTRAINT orders_check;"
        " ALTER TABLE orders ADD CONSTRAINT orders_check CHECK ("
        "  (kind = 'upgrade' AND choice IS NULL)"
        "  OR (kind = 'policy_vote' AND choice IN ('balanced', 'industrial'))"
        "  OR (kind = 'work' AND choice IN ('smelter')));"
        " DELETE FROM city_works WHERE kind <> 'smelter';"
        " ALTER TABLE city_works DROP CONSTRAINT city_works_kind_check;"
        " ALTER TABLE city_works ADD CONSTRAINT city_works_kind_check CHECK (kind = 'smelter');"
        " ALTER TABLE city_works DROP CONSTRAINT city_works_idle_fits, DROP COLUMN idle;"
        " ALTER TABLE cities DROP CONSTRAINT cities_site_complete;"
        " ALTER TABLE cities DROP COLUMN site_heat, DROP COLUMN site_water,"
        "  DROP COLUMN site_sun, DROP COLUMN site_wind;"
        " ALTER TABLE cities ADD CONSTRAINT cities_site_complete CHECK ("
        "  num_nulls(site_food, site_timber, site_stone, site_ore, site_effort, site_room)"
        "  IN (0, 6))"
    )
