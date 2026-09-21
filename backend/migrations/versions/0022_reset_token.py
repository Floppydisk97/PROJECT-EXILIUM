"""Il segno di un azzeramento gia' fatto, perche' una variabile dimenticata sia innocua."""
from pathlib import Path

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade():
    op.get_bind().exec_driver_sql("ALTER TABLE world DROP COLUMN last_reset_token")
