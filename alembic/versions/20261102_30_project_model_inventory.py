"""Replace scenario-scoped assignments with a project model inventory.

This test-stage contract intentionally does not migrate legacy assignment rows.
Do not apply to a live database without a separately approved data plan.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261102_30"
down_revision = "20261029_29"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("project_model_assignments")
    op.create_table(
        "project_model_assignments",
        sa.Column("assignment_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("parameter_profile_key", sa.String(512), nullable=True),
        sa.Column("parameter_platform", sa.String(16), nullable=False, server_default="server"),
        sa.Column("parameter_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parameter_snapshot", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_account_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_account_id"], ["accounts.account_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["project_id", "parameter_profile_key"],
            ["model_parameter_profiles.project_id", "model_parameter_profiles.profile_key"],
            ondelete="RESTRICT",
            name="fk_project_model_assignments_project_profile",
        ),
        sa.CheckConstraint("parameter_platform IN ('android', 'server')", name="ck_project_model_assignment_platform"),
        sa.CheckConstraint("parameter_revision >= 0", name="ck_project_model_assignment_parameter_revision"),
        sa.UniqueConstraint(
            "project_id", "model_id", "model_version", "parameter_platform",
            name="uq_project_model_assignments_project_model_target",
        ),
    )
    op.create_index("ix_project_model_assignments_project_id", "project_model_assignments", ["project_id"])
    op.create_index("ix_project_model_assignments_model_id", "project_model_assignments", ["model_id"])
    op.create_index("ix_project_model_assignments_enabled", "project_model_assignments", ["enabled"])
    op.create_index("ix_project_model_assignments_project_enabled", "project_model_assignments", ["project_id", "enabled"])


def downgrade():
    raise RuntimeError(
        "project model inventory downgrade is unsupported; recreate an isolated test database instead"
    )
