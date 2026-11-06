"""Project-bound non-human credentials and shared replay protection."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261012_10"
down_revision = "20261012_09"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "service_principals",
        sa.Column("principal_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("principal_type", sa.String(16), nullable=False),
        sa.Column("capabilities", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("credential_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by_account_id", sa.String(36), sa.ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "principal_id", name="uq_service_principals_project_id"),
        sa.CheckConstraint("principal_type IN ('DEVICE', 'SERVICE')", name="ck_service_principals_type"),
        sa.CheckConstraint("revision >= 1", name="ck_service_principals_revision"),
    )
    op.create_index("ix_service_principals_project_id", "service_principals", ["project_id"])
    op.create_table(
        "service_request_nonces",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("principal_id", sa.String(36), primary_key=True),
        sa.Column("nonce_digest", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "principal_id"], ["service_principals.project_id", "service_principals.principal_id"], ondelete="CASCADE", name="fk_service_nonce_project_principal"),
    )
    op.create_index("ix_service_request_nonces_expires_at", "service_request_nonces", ["expires_at"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM service_principals")).scalar_one():
        raise RuntimeError("service credential downgrade refused: principals exist; export and review before rollback")
    op.drop_table("service_request_nonces")
    op.drop_table("service_principals")
