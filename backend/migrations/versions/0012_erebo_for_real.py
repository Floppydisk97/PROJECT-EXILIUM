"""Reset the map again: 0011 shipped the new size but not the new seed."""
from pathlib import Path

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
