"""Persist approved per-plan mobile camera scheduling policy."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_33"
down_revision = "20261102_32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_scene_plans", sa.Column("camera_policy", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("project_scene_plans", "camera_policy")
