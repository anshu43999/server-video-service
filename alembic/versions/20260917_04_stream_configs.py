"""Persist stream control-plane configuration.

Revision ID: 20260917_04
Revises: 20260915_03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_04"
down_revision: Union[str, None] = "20260915_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stream_configs",
        sa.Column("stream_id", sa.String(128), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("model_id", sa.String(255), nullable=True),
        sa.Column("yolo_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("max_fps", sa.Float(), nullable=False),
        sa.Column("overlay_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_stream_configs_model_id", "stream_configs", ["model_id"])
    op.create_index("ix_stream_configs_enabled", "stream_configs", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_stream_configs_enabled", table_name="stream_configs")
    op.drop_index("ix_stream_configs_model_id", table_name="stream_configs")
    op.drop_table("stream_configs")
