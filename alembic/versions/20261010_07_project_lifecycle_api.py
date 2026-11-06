"""Add account revisions and platform audit storage.

Revision ID: 20261010_07
Revises: 20261010_06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261010_07"
down_revision: Union[str, None] = "20261010_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JsonDocument = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))

    op.create_table(
        "platform_audit_events",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("actor_account_id", sa.String(36), nullable=True),
        sa.Column("platform_role", sa.String(32), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(128), nullable=False),
        sa.Column("target_id", sa.String(512), nullable=True),
        sa.Column("previous_revision", sa.Integer(), nullable=True),
        sa.Column("new_revision", sa.Integer(), nullable=True),
        sa.Column("change_summary", JsonDocument, nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.account_id"], ondelete="SET NULL",
            name="fk_platform_audit_events_actor_account_id_accounts",
        ),
        sa.CheckConstraint(
            "outcome IN ('SUCCESS', 'DENIED', 'FAILED')",
            name="ck_platform_audit_events_outcome",
        ),
    )
    op.create_index("ix_platform_audit_events_occurred_at", "platform_audit_events", ["occurred_at"])
    op.create_index("ix_platform_audit_events_request_id", "platform_audit_events", ["request_id"])
    op.create_index("ix_platform_audit_events_actor_account_id", "platform_audit_events", ["actor_account_id"])
    op.create_index("ix_platform_audit_events_action", "platform_audit_events", ["action"])
    op.create_index("ix_platform_audit_events_target", "platform_audit_events", ["target_type", "target_id"])


def downgrade() -> None:
    bind = op.get_bind()
    audit_count = int(bind.execute(sa.text("SELECT COUNT(*) FROM platform_audit_events")).scalar_one())
    if audit_count:
        raise RuntimeError("project lifecycle API downgrade refused because it would discard platform audit history")
    op.drop_table("platform_audit_events")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("revision")
