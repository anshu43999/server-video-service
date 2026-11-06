"""Persist short-lived, exact-scope suite runtime grants."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261021_20"
down_revision = "20261021_19"
branch_labels = None
depends_on = None


def upgrade():
    document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "project_scene_runtime_grants",
        sa.Column("grant_id", sa.String(36), primary_key=True),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("scene_id", sa.String(128), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("scene_revision", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("member_id", sa.String(128), nullable=False),
        sa.Column("input_type", sa.String(16), nullable=False),
        sa.Column("target", sa.String(16), nullable=False),
        sa.Column("client_contract_version", sa.Integer(), nullable=False),
        sa.Column("supported_execution_modes", document, nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("artifact_id", sa.String(255), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("parameter_revision", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id", "scene_id"], ["project_scenes.project_id", "project_scenes.scene_id"],
            ondelete="CASCADE", name="fk_scene_runtime_grants_project_scene",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "scene_id", "member_id"],
            ["project_scene_members.project_id", "project_scene_members.scene_id", "project_scene_members.member_id"],
            ondelete="CASCADE", name="fk_scene_runtime_grants_scene_member",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"],
                                ondelete="CASCADE", name="fk_scene_runtime_grants_account"),
        sa.CheckConstraint("scene_revision >= 1", name="ck_scene_runtime_grant_revision"),
        sa.CheckConstraint("input_type IN ('image', 'video')", name="ck_scene_runtime_grant_input"),
        sa.CheckConstraint("target IN ('pc', 'mobile')", name="ck_scene_runtime_grant_target"),
        sa.CheckConstraint("parameter_revision >= 0", name="ck_scene_runtime_grant_parameter_revision"),
    )
    op.create_index("ix_project_scene_runtime_grants_expires_at",
                    "project_scene_runtime_grants", ["expires_at"])
    op.create_index("ix_scene_runtime_grants_scope_expiry",
                    "project_scene_runtime_grants", ["project_id", "scene_id", "account_id", "expires_at"])

def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM project_scene_runtime_grants")).scalar_one():
        raise RuntimeError("runtime grant downgrade refused: grant records exist")
    op.drop_index("ix_scene_runtime_grants_scope_expiry", table_name="project_scene_runtime_grants")
    op.drop_index("ix_project_scene_runtime_grants_expires_at", table_name="project_scene_runtime_grants")
    op.drop_table("project_scene_runtime_grants")
