"""Add accounts and opaque login sessions.

Revision ID: 20260915_03
Revises: 20260914_02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_03"
down_revision: Union[str, None] = "20260914_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("username", sa.String(128), primary_key=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_accounts_role", "accounts", ["role"])
    op.create_index("ix_accounts_enabled", "accounts", ["enabled"])
    op.create_table(
        "account_sessions",
        sa.Column("session_hash", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["username"], ["accounts.username"], ondelete="CASCADE"),
    )
    op.create_index("ix_account_sessions_username", "account_sessions", ["username"])
    op.create_index("ix_account_sessions_role", "account_sessions", ["role"])
    op.create_index("ix_account_sessions_expires_at", "account_sessions", ["expires_at"])
    op.create_index("ix_account_sessions_revoked_at", "account_sessions", ["revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_account_sessions_revoked_at", table_name="account_sessions")
    op.drop_index("ix_account_sessions_expires_at", table_name="account_sessions")
    op.drop_index("ix_account_sessions_role", table_name="account_sessions")
    op.drop_index("ix_account_sessions_username", table_name="account_sessions")
    op.drop_table("account_sessions")
    op.drop_index("ix_accounts_enabled", table_name="accounts")
    op.drop_index("ix_accounts_role", table_name="accounts")
    op.drop_table("accounts")
