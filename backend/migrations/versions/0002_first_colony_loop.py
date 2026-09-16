"""First playable colony loop."""
import hashlib
import json
from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    connection = op.get_bind()
    connection.exec_driver_sql(sql)
    orders = connection.exec_driver_sql(
        """SELECT o.id, o.idempotency_key, o.kind, o.choice, o.submitted_at,
                  c.owner_id, o.city_id
           FROM orders o JOIN cities c ON c.id = o.city_id ORDER BY o.id"""
    ).mappings()
    for order in orders:
        payload = {"choice": order["choice"], "city_id": str(order["city_id"]), "kind": order["kind"]}
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result = json.dumps({"order_id": str(order["id"])})
        connection.exec_driver_sql(
            """INSERT INTO idempotency_records
                   (player_id, idempotency_key, action_kind, payload_hash, result, created_at)
               VALUES (%s, %s, 'strategic_order', %s, %s::jsonb, %s)""",
            (order["owner_id"], order["idempotency_key"], fingerprint, result, order["submitted_at"]),
        )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
