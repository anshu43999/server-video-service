"""Durable APK upload jobs and immutable object identity (M42-T03)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261029_28"
down_revision = "20261029_27"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_artifact_sources", sa.Column("object_version_id", sa.String(255)))
    op.add_column("app_artifact_sources", sa.Column("object_etag", sa.String(255)))
    op.create_table("app_apk_uploads",
        sa.Column("upload_id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("artifact_id", sa.String(128), sa.ForeignKey("app_artifacts.artifact_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("resolved_artifact_id", sa.String(128), sa.ForeignKey("app_artifacts.artifact_id", ondelete="RESTRICT")),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("size_bytes", sa.BigInteger()), sa.Column("sha256", sa.String(64)),
        sa.Column("request_sha256", sa.String(64)),
        sa.Column("compatibility", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("reason", sa.String(1000)), sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("error_code", sa.String(128)),
        sa.Column("cleanup_pending", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_app_upload_idempotency"),
        sa.CheckConstraint("state IN ('receiving', 'queued', 'processing', 'retryable', 'succeeded', 'failed')", name="ck_app_upload_state"),
        sa.CheckConstraint("attempts >= 0 AND (size_bytes IS NULL OR size_bytes BETWEEN 1 AND 8589934592)", name="ck_app_upload_size"))
    op.create_index("ix_app_upload_state_lease", "app_apk_uploads", ["state", "lease_until"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM app_apk_uploads LIMIT 1")).first() or connection.execute(sa.text(
        "SELECT 1 FROM app_artifact_sources WHERE object_version_id IS NOT NULL OR object_etag IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("APK upload downgrade refused: durable history exists")
    op.drop_table("app_apk_uploads")
    op.drop_column("app_artifact_sources", "object_etag")
    op.drop_column("app_artifact_sources", "object_version_id")
