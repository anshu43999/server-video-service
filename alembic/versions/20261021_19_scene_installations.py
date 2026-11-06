"""Persist account-scoped scene installation preparation projections."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261021_19"
down_revision = "20261021_18"
branch_labels = None
depends_on = None


def upgrade():
    document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "project_scene_installations",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("scene_id", sa.String(128), primary_key=True),
        sa.Column("account_id", sa.String(36), primary_key=True),
        sa.Column("target", sa.String(16), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("selection_key", sa.String(256), primary_key=True),
        sa.Column("plan_id", sa.String(128), nullable=True),
        sa.Column("member_id", sa.String(128), nullable=True),
        sa.Column("required_member_ids", document, nullable=False),
        sa.Column("ready_member_ids", document, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="not_installed"),
        sa.Column("last_error", document, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["project_id", "scene_id"],
            ["project_scenes.project_id", "project_scenes.scene_id"],
            ondelete="CASCADE", name="fk_scene_installations_project_scene",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.account_id"],
            ondelete="CASCADE", name="fk_scene_installations_account",
        ),
        sa.CheckConstraint("target IN ('pc', 'mobile')", name="ck_scene_installations_target"),
        sa.CheckConstraint(
            "status IN ('not_installed', 'preparing', 'partial', 'ready', 'stale', 'failed', 'blocked')",
            name="ck_scene_installations_status",
        ),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM project_scene_installations")).scalar_one():
        raise RuntimeError("scene installation downgrade refused: preparation records exist")
    op.drop_table("project_scene_installations")
