"""The world clock: a speed the simulation reads, so a day can be made to pass in minutes."""
from pathlib import Path

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade():
    op.get_bind().exec_driver_sql(
        "ALTER TABLE world"
        " DROP CONSTRAINT world_time_speed_positive,"
        " DROP COLUMN time_anchor_world,"
        " DROP COLUMN time_anchor_real,"
        " DROP COLUMN time_speed"
    )
