"""Persistent scene tombstones and recoverable resource lifecycle operations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_22"
down_revision = "20261022_21"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("project_scenes", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("project_scenes", sa.Column("deletion_operation_id", sa.String(36), nullable=True))
    document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table("resource_lifecycle_operations",
        sa.Column("operation_id", sa.String(36), primary_key=True),
        sa.Column("request_key", sa.String(64), nullable=False, unique=True),
        sa.Column("scope_key", sa.String(512), nullable=False, index=True),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("payload", document, nullable=False),
        sa.Column("result", document, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("resource_lifecycle_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("operation_id", sa.String(36), nullable=True, index=True),
        sa.Column("scope_key", sa.String(512), nullable=False, index=True),
        sa.Column("lifecycle_revision", sa.Integer(), nullable=False),
        sa.Column("payload", document, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    connection = op.get_bind()
    for table in ("resource_lifecycle_operations", "resource_lifecycle_events"):
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError("resource lifecycle downgrade refused: durable facts exist")
    if connection.execute(sa.text("SELECT COUNT(*) FROM project_scenes WHERE deleted_at IS NOT NULL")).scalar_one():
        raise RuntimeError("resource lifecycle downgrade refused: scene tombstones exist")
    op.drop_table("resource_lifecycle_events")
    op.drop_table("resource_lifecycle_operations")
    op.drop_column("project_scenes", "deletion_operation_id")
    op.drop_column("project_scenes", "deleted_at")
