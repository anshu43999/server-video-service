"""Bind scene members to project model inventory identities.

Test-stage migration: legacy scene data is intentionally discarded rather than
translated from global model references into project authorization records.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261102_31"
down_revision = "20261102_30"
branch_labels = None
depends_on = None


def _clear_scene_data():
    bind = op.get_bind()
    for table in (
        "project_scene_runtime_grants",
        "project_scene_installations",
        "project_scene_plan_members",
        "project_scene_plans",
        "project_scene_members",
        "project_scenes",
    ):
        bind.execute(sa.text(f"DELETE FROM {table}"))


def upgrade():
    _clear_scene_data()
    with op.batch_alter_table("project_scene_members") as batch:
        batch.add_column(sa.Column("project_model_id", sa.String(36), nullable=False))
        batch.add_column(sa.Column("parameter_revision", sa.Integer(), nullable=False, server_default="0"))
        batch.create_foreign_key(
            "fk_scene_members_project_model", "project_model_assignments",
            ["project_model_id"], ["assignment_id"], ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_scene_member_project_model",
            ["project_id", "scene_id", "project_model_id"],
        )
        batch.create_check_constraint(
            "ck_scene_member_parameter_revision", "parameter_revision >= 0"
        )


def downgrade():
    _clear_scene_data()
    with op.batch_alter_table("project_scene_members") as batch:
        batch.drop_constraint("ck_scene_member_parameter_revision", type_="check")
        batch.drop_constraint("uq_scene_member_project_model", type_="unique")
        batch.drop_constraint("fk_scene_members_project_model", type_="foreignkey")
        batch.drop_column("project_model_id")
        batch.drop_column("parameter_revision")
