"""Persist the explicit approved scene plan selected by each stream."""
from alembic import op
import sqlalchemy as sa


revision = "20261102_32"
down_revision = "20261102_31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stream_configs", sa.Column("scene_id", sa.String(length=128), nullable=True))
    op.add_column("stream_configs", sa.Column("plan_id", sa.String(length=128), nullable=True))
    op.add_column("stream_configs", sa.Column("scene_revision", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("stream_configs", "scene_revision")
    op.drop_column("stream_configs", "plan_id")
    op.drop_column("stream_configs", "scene_id")
