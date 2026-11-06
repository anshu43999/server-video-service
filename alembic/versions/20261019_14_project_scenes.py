"""Project-scoped scenes, ordered members and independent revisions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261019_14"
down_revision = "20261019_13"
branch_labels = None
depends_on = None


def upgrade():
    document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "project_scenes",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.project_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("scene_id", sa.String(128), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("input_types", document, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_account_id", sa.String(36), sa.ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("revision >= 1", name="ck_project_scene_revision"),
    )
    op.create_table(
        "project_scene_members",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("scene_id", sa.String(128), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("target", sa.String(16), nullable=False),
        sa.Column("execution", sa.String(16), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "scene_id"], ["project_scenes.project_id", "project_scenes.scene_id"], ondelete="CASCADE", name="fk_scene_members_project_scene"),
        sa.UniqueConstraint("project_id", "scene_id", "model_id", "model_version", "target", name="uq_scene_member_release_target"),
        sa.CheckConstraint("position >= 0", name="ck_scene_member_position"),
        sa.CheckConstraint("target IN ('pc', 'mobile')", name="ck_scene_member_target"),
        sa.CheckConstraint("execution IN ('single', 'sync', 'async')", name="ck_scene_member_execution"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM project_scenes")).scalar_one():
        raise RuntimeError("scene downgrade refused: project scene data exists")
    op.drop_table("project_scene_members")
    op.drop_table("project_scenes")
