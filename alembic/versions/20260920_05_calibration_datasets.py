"""Persist versioned calibration dataset metadata.

Revision ID: 20260920_05
Revises: 20260917_04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260920_05"
down_revision: Union[str, None] = "20260917_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calibration_datasets",
        sa.Column("dataset_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("scenario", sa.String(100), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("yaml_path", sa.String(512), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_calibration_dataset_name_version"),
    )
    op.create_index("ix_calibration_datasets_scenario", "calibration_datasets", ["scenario"])


def downgrade() -> None:
    op.drop_index("ix_calibration_datasets_scenario", table_name="calibration_datasets")
    op.drop_table("calibration_datasets")
