"""Retain deleted scene inventory identities after project model removal.

No business records are removed or detached by this migration. The application
archives references only when explicitly removing a model whose scenes are all
soft-deleted; live scene references retain their RESTRICT foreign key.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261117_35"
down_revision = "20261105_34"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("project_scene_members") as batch:
        batch.add_column(sa.Column("archived_project_model_id", sa.String(36), nullable=True))
        batch.alter_column("project_model_id", existing_type=sa.String(36), nullable=True)
        batch.create_check_constraint(
            "ck_scene_member_inventory_identity",
            "(project_model_id IS NOT NULL AND archived_project_model_id IS NULL) OR "
            "(project_model_id IS NULL AND archived_project_model_id IS NOT NULL)",
        )


def downgrade():
    raise RuntimeError(
        "scene history inventory downgrade is unsupported; retained audit identities must not be discarded"
    )
