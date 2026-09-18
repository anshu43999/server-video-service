"""Create alert persistence tables.

Revision ID: 20260914_01
Revises: None
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260914_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_events",
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("rule_id", sa.String(length=255), nullable=True),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("subject_key", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=True),
        sa.Column("disposition_status", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_alert_events_disposition_status", "alert_events", ["disposition_status"])
    op.create_index("ix_alert_events_severity", "alert_events", ["severity"])
    op.create_index("ix_alert_events_source_id", "alert_events", ["source_id"])
    op.create_index("ix_alert_events_updated_at", "alert_events", ["updated_at"])

    op.create_table(
        "alert_disposition_actions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("acted_at_us", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["alert_events.event_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "status", "actor", "acted_at_us", name="uq_alert_disposition_action"),
    )
    op.create_index("ix_alert_disposition_actions_event_id", "alert_disposition_actions", ["event_id"])

    op.create_table(
        "false_positive_feedback",
        sa.Column("entry_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("action_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["alert_disposition_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["alert_events.event_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entry_id"),
        sa.UniqueConstraint("action_id"),
    )
    op.create_index("ix_false_positive_feedback_event_id", "false_positive_feedback", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_false_positive_feedback_event_id", table_name="false_positive_feedback")
    op.drop_table("false_positive_feedback")
    op.drop_index("ix_alert_disposition_actions_event_id", table_name="alert_disposition_actions")
    op.drop_table("alert_disposition_actions")
    op.drop_index("ix_alert_events_updated_at", table_name="alert_events")
    op.drop_index("ix_alert_events_source_id", table_name="alert_events")
    op.drop_index("ix_alert_events_severity", table_name="alert_events")
    op.drop_index("ix_alert_events_disposition_status", table_name="alert_events")
    op.drop_table("alert_events")
