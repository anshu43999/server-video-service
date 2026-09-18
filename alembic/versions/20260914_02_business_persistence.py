"""Persist mutable backend business state.

Revision ID: 20260914_02
Revises: 20260914_01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260914_02"
down_revision: Union[str, None] = "20260914_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "alert_rules",
        sa.Column("rule_id", sa.String(64), primary_key=True),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_alert_rules_enabled", "alert_rules", ["enabled"])
    op.create_table(
        "alert_rule_bindings",
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.rule_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rule_id", "source_id"),
    )
    op.create_index("ix_alert_rule_bindings_accepted", "alert_rule_bindings", ["accepted"])
    op.create_table(
        "alert_rule_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_alert_rule_audits_rule_id", "alert_rule_audits", ["rule_id"])
    op.create_index("ix_alert_rule_audits_action", "alert_rule_audits", ["action"])

    op.create_table(
        "model_parameter_profiles",
        sa.Column("profile_key", sa.String(512), primary_key=True),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("model_id", "model_version", "platform", name="uq_model_parameter_profile"),
    )
    op.create_index("ix_model_parameter_profiles_model_id", "model_parameter_profiles", ["model_id"])
    op.create_index("ix_model_parameter_profiles_platform", "model_parameter_profiles", ["platform"])
    op.create_table(
        "model_parameter_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("profile_key", sa.String(512), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["profile_key"], ["model_parameter_profiles.profile_key"], ondelete="CASCADE"),
    )
    op.create_index("ix_model_parameter_audits_profile_key", "model_parameter_audits", ["profile_key"])

    op.create_table(
        "alert_verification_config",
        sa.Column("config_key", sa.String(32), primary_key=True),
        sa.Column("calls_day", sa.Integer(), nullable=False),
        sa.Column("calls_today", sa.Integer(), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "alert_verifications",
        sa.Column("event_id", sa.String(255), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["alert_events.event_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_alert_verifications_status", "alert_verifications", ["status"])
    op.create_table(
        "alert_delivery_receipts",
        sa.Column("delivery_id", sa.String(64), primary_key=True),
        sa.Column("event_id", sa.String(255), nullable=True),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_alert_delivery_receipts_event_id", "alert_delivery_receipts", ["event_id"])
    op.create_index("ix_alert_delivery_receipts_channel", "alert_delivery_receipts", ["channel"])
    op.create_index("ix_alert_delivery_receipts_status", "alert_delivery_receipts", ["status"])

    op.create_table(
        "conversion_config",
        sa.Column("config_key", sa.String(32), primary_key=True),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "conversion_jobs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_epoch", sa.Float(), nullable=False),
        sa.Column("updated_epoch", sa.Float(), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_conversion_jobs_action", "conversion_jobs", ["action"])
    op.create_index("ix_conversion_jobs_status", "conversion_jobs", ["status"])
    op.create_index("ix_conversion_jobs_created_epoch", "conversion_jobs", ["created_epoch"])


def downgrade() -> None:
    op.drop_index("ix_conversion_jobs_created_epoch", table_name="conversion_jobs")
    op.drop_index("ix_conversion_jobs_status", table_name="conversion_jobs")
    op.drop_index("ix_conversion_jobs_action", table_name="conversion_jobs")
    op.drop_table("conversion_jobs")
    op.drop_table("conversion_config")
    op.drop_index("ix_alert_delivery_receipts_status", table_name="alert_delivery_receipts")
    op.drop_index("ix_alert_delivery_receipts_channel", table_name="alert_delivery_receipts")
    op.drop_index("ix_alert_delivery_receipts_event_id", table_name="alert_delivery_receipts")
    op.drop_table("alert_delivery_receipts")
    op.drop_index("ix_alert_verifications_status", table_name="alert_verifications")
    op.drop_table("alert_verifications")
    op.drop_table("alert_verification_config")
    op.drop_index("ix_model_parameter_audits_profile_key", table_name="model_parameter_audits")
    op.drop_table("model_parameter_audits")
    op.drop_index("ix_model_parameter_profiles_platform", table_name="model_parameter_profiles")
    op.drop_index("ix_model_parameter_profiles_model_id", table_name="model_parameter_profiles")
    op.drop_table("model_parameter_profiles")
    op.drop_index("ix_alert_rule_audits_action", table_name="alert_rule_audits")
    op.drop_index("ix_alert_rule_audits_rule_id", table_name="alert_rule_audits")
    op.drop_table("alert_rule_audits")
    op.drop_index("ix_alert_rule_bindings_accepted", table_name="alert_rule_bindings")
    op.drop_table("alert_rule_bindings")
    op.drop_index("ix_alert_rules_enabled", table_name="alert_rules")
    op.drop_table("alert_rules")
