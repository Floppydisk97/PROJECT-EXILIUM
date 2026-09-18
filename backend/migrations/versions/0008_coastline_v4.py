"""Generator v4: seeded island arcs and isotropic rift basis; reset authoritative map."""
from pathlib import Path

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade():
    raise RuntimeError(
        "0008 deletes the previous map; restore the verified pre-0008 backup as documented"
    )
