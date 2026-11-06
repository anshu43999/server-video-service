"""Add mobile disposition operation idempotency."""
from alembic import op
import sqlalchemy as sa

revision = "20261019_15"
down_revision = "20261019_14"
branch_labels = None
depends_on = None


def upgrade():
    # Direct additive DDL avoids SQLite batch-copy reordering cycles caused by
    # the table's existing mixed timestamp/default column metadata.
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("alert_disposition_actions")}
    if "operation_id" not in columns:
        op.add_column("alert_disposition_actions", sa.Column("operation_id", sa.String(36), nullable=True))
    if "request_digest" not in columns:
        op.add_column("alert_disposition_actions", sa.Column("request_digest", sa.String(64), nullable=True))
    names = {item["name"] for item in inspector.get_indexes("alert_disposition_actions")}
    names.update(item["name"] for item in inspector.get_unique_constraints("alert_disposition_actions"))
    if "uq_alert_disposition_operation" not in names:
        op.create_index(
            "uq_alert_disposition_operation", "alert_disposition_actions",
            ["project_id", "event_id", "operation_id"], unique=True,
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    # SQLite exposes table-level UNIQUE constraints through the inspector even
    # though their backing auto-index cannot be dropped by the constraint name.
    # Only remove an index that the migration can address explicitly.
    index_names = {item["name"] for item in inspector.get_indexes("alert_disposition_actions")}
    owns_columns = "uq_alert_disposition_operation" in index_names
    if owns_columns:
        op.drop_index("uq_alert_disposition_operation", table_name="alert_disposition_actions")
    else:
        return
    columns = {item["name"] for item in inspector.get_columns("alert_disposition_actions")}
    if "request_digest" in columns:
        op.drop_column("alert_disposition_actions", "request_digest")
    if "operation_id" in columns:
        op.drop_column("alert_disposition_actions", "operation_id")
