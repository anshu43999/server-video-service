from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, Text, UniqueConstraint, create_engine, event, func, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


JsonDocument = JSON().with_variant(JSONB, "postgresql")
RecordId = BigInteger().with_variant(Integer, "sqlite")
DEFAULT_PROJECT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_PROJECT_CODE = "legacy-default"


def _new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class AccountRecord(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    platform_role: Mapped[str] = mapped_column(String(32), nullable=False, default="NORMAL_USER", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AccountSessionRecord(Base):
    __tablename__ = "account_sessions"

    session_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProjectRecord(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('ACTIVE', 'SUSPENDED', 'ARCHIVED')",
            name="ck_projects_lifecycle_state",
        ),
    )


class ProjectMembershipRecord(Base):
    __tablename__ = "project_memberships"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.account_id", ondelete="CASCADE"), primary_key=True
    )
    project_role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "project_role IN ('PROJECT_OWNER', 'PROJECT_USER')",
            name="ck_project_memberships_role",
        ),
        Index("ix_project_memberships_account_enabled", "account_id", "enabled"),
    )


class AlertEventRecord(Base):
    __tablename__ = "alert_events"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True,
        default=DEFAULT_PROJECT_ID, index=True
    )
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    rule_id: Mapped[str | None] = mapped_column(String(255))
    source_id: Mapped[str | None] = mapped_column(String(255), index=True)
    subject_key: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(32))
    severity: Mapped[str | None] = mapped_column(String(32), index=True)
    disposition_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="OPEN")
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("project_id", "event_id", name="uq_alert_events_project_event"),
        Index("ix_alert_events_updated_at", "updated_at"),
        Index("ix_alert_events_project_updated", "project_id", "updated_at"),
        Index("ix_alert_events_project_created", "project_id", "created_at"),
    )


class AlertDispositionActionRecord(Base):
    __tablename__ = "alert_disposition_actions"

    id: Mapped[int] = mapped_column(RecordId, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False,
        default=DEFAULT_PROJECT_ID, index=True
    )
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acted_at_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "event_id"],
            ["alert_events.project_id", "alert_events.event_id"],
            ondelete="CASCADE",
            name="fk_alert_disposition_actions_project_event",
        ),
        UniqueConstraint("project_id", "id", name="uq_alert_disposition_actions_project_id"),
        UniqueConstraint(
            "project_id", "event_id", "status", "actor", "acted_at_us",
            name="uq_alert_disposition_action",
        ),
        Index(
            "uq_alert_disposition_operation", "project_id", "event_id", "operation_id",
            unique=True,
        ),
        Index("ix_alert_disposition_actions_project_event", "project_id", "event_id"),
    )


class FalsePositiveFeedbackRecord(Base):
    __tablename__ = "false_positive_feedback"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True,
        default=DEFAULT_PROJECT_ID, index=True
    )
    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    action_id: Mapped[int] = mapped_column(RecordId, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "event_id"],
            ["alert_events.project_id", "alert_events.event_id"],
            ondelete="CASCADE",
            name="fk_false_positive_feedback_project_event",
        ),
        ForeignKeyConstraint(
            ["project_id", "action_id"],
            ["alert_disposition_actions.project_id", "alert_disposition_actions.id"],
            ondelete="CASCADE",
            name="fk_false_positive_feedback_project_action",
        ),
        UniqueConstraint("project_id", "entry_id", name="uq_false_positive_feedback_project_entry"),
        UniqueConstraint("project_id", "action_id", name="uq_false_positive_feedback_project_action"),
    )


class AlertRuleRecord(Base):
    __tablename__ = "alert_rules"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True,
        default=DEFAULT_PROJECT_ID, index=True
    )
    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("project_id", "rule_id", name="uq_alert_rules_project_rule"),
        Index("ix_alert_rules_project_enabled", "project_id", "enabled"),
    )


class AlertRuleBindingRecord(Base):
    __tablename__ = "alert_rule_bindings"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True,
        default=DEFAULT_PROJECT_ID, index=True
    )
    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "rule_id"],
            ["alert_rules.project_id", "alert_rules.rule_id"],
            ondelete="CASCADE",
            name="fk_alert_rule_bindings_project_rule",
        ),
        Index("ix_alert_rule_bindings_project_source", "project_id", "source_id"),
    )


class AlertRuleAuditRecord(Base):
    __tablename__ = "alert_rule_audits"

    id: Mapped[int] = mapped_column(RecordId, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False,
        default=DEFAULT_PROJECT_ID, index=True
    )
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_alert_rule_audits_project_rule", "project_id", "rule_id"),)


class ModelParameterProfileRecord(Base):
    __tablename__ = "model_parameter_profiles"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True,
        default=DEFAULT_PROJECT_ID, index=True
    )
    profile_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="PLATFORM")
    model_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("scope IN ('PLATFORM', 'PROJECT')", name="ck_model_parameter_profiles_scope"),
        UniqueConstraint("project_id", "profile_key", name="uq_model_parameter_profiles_project_key"),
        UniqueConstraint(
            "project_id", "scope", "model_id", "model_version", "platform", name="uq_model_parameter_profile"
        ),
        Index("ix_model_parameter_profiles_project_model", "project_id", "model_id"),
    )


class ModelParameterAuditRecord(Base):
    __tablename__ = "model_parameter_audits"

    id: Mapped[int] = mapped_column(RecordId, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False,
        default=DEFAULT_PROJECT_ID, index=True
    )
    profile_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "profile_key"],
            ["model_parameter_profiles.project_id", "model_parameter_profiles.profile_key"],
            ondelete="CASCADE",
            name="fk_model_parameter_audits_project_profile",
        ),
        Index("ix_model_parameter_audits_project_profile", "project_id", "profile_key"),
    )


class AlertVerificationConfigRecord(Base):
    __tablename__ = "alert_verification_config"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True,
        default=DEFAULT_PROJECT_ID, index=True
    )
    config_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    calls_day: Mapped[int] = mapped_column(Integer, nullable=False)
    calls_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("project_id", "config_key", name="uq_alert_verification_config_project_key"),
    )


class AlertVerificationRecord(Base):
    __tablename__ = "alert_verifications"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True,
        default=DEFAULT_PROJECT_ID, index=True
    )
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "event_id"],
            ["alert_events.project_id", "alert_events.event_id"],
            ondelete="CASCADE",
            name="fk_alert_verifications_project_event",
        ),
        UniqueConstraint("project_id", "event_id", name="uq_alert_verifications_project_event"),
    )


class AlertDeliveryReceiptRecord(Base):
    __tablename__ = "alert_delivery_receipts"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True,
        default=DEFAULT_PROJECT_ID, index=True
    )
    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "event_id"],
            ["alert_events.project_id", "alert_events.event_id"],
            ondelete="RESTRICT",
            name="fk_alert_delivery_receipts_project_event",
        ),
        UniqueConstraint("project_id", "delivery_id", name="uq_alert_delivery_receipts_project_delivery"),
        Index("ix_alert_delivery_receipts_project_created", "project_id", "created_at"),
    )


class SystemKnowledgeCatalogRecord(Base):
    __tablename__ = "system_knowledge_catalog"
    catalog_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class SystemKnowledgeReleaseRecord(Base):
    __tablename__ = "system_knowledge_releases"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ProjectKnowledgeBaseRecord(Base):
    __tablename__ = "project_knowledge_bases"
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, ForeignKey("system_knowledge_releases.version", ondelete="RESTRICT"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class AlertAdviceKnowledgeEntryRecord(Base):
    __tablename__ = "alert_advice_knowledge_entries"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True
    )
    entry_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    alert_type_id: Mapped[str] = mapped_column(String(128), nullable=False)
    recognition_category_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_alert_advice_knowledge_status"),
        UniqueConstraint(
            "project_id", "alert_type_id", "recognition_category_id",
            name="uq_alert_advice_knowledge_match_key",
        ),
        Index("ix_alert_advice_knowledge_project_status", "project_id", "status"),
        Index(
            "ix_alert_advice_knowledge_project_match", "project_id",
            "alert_type_id", "recognition_category_id",
        ),
    )


class AlertAdviceKnowledgeRevisionRecord(Base):
    __tablename__ = "alert_advice_knowledge_revisions"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entry_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "entry_id"],
            ["alert_advice_knowledge_entries.project_id", "alert_advice_knowledge_entries.entry_id"],
            ondelete="RESTRICT", name="fk_alert_advice_revision_entry",
        ),
        CheckConstraint("action IN ('CREATE', 'UPDATE', 'ACTIVATE', 'DEACTIVATE')", name="ck_alert_advice_revision_action"),
        Index("ix_alert_advice_revisions_project_entry", "project_id", "entry_id", "revision"),
    )


class AlertAdviceGenerationRecord(Base):
    __tablename__ = "alert_advice_generations"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    generation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(36), nullable=False)
    retry_of_generation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "event_id"], ["alert_events.project_id", "alert_events.event_id"],
            ondelete="RESTRICT", name="fk_alert_advice_generation_event",
        ),
        UniqueConstraint(
            "project_id", "event_id", "idempotency_key",
            name="uq_alert_advice_generation_idempotency",
        ),
        CheckConstraint(
            "status IN ('GENERATED', 'NO_MATCH', 'PARTIAL', 'FAILED_RETRIEVAL', 'FAILED_GENERATION')",
            name="ck_alert_advice_generation_status",
        ),
        Index(
            "ix_alert_advice_generation_project_event_created", "project_id", "event_id", "created_at",
        ),
    )


class ProjectBusinessConfigRecord(Base):
    __tablename__ = "project_business_config"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True
    )
    config_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (CheckConstraint("revision >= 1", name="ck_project_business_config_revision"),)


class ProjectModelAssignmentRecord(Base):
    __tablename__ = "project_model_assignments"

    assignment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    parameter_profile_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parameter_platform: Mapped[str] = mapped_column(String(16), nullable=False, default="server")
    parameter_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parameter_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "parameter_profile_key"],
            ["model_parameter_profiles.project_id", "model_parameter_profiles.profile_key"],
            ondelete="RESTRICT",
            name="fk_project_model_assignments_project_profile",
        ),
        UniqueConstraint("project_id", "model_id", "model_version", "parameter_platform", name="uq_project_model_assignments_project_model_target"),
        CheckConstraint("parameter_platform IN ('android', 'server')", name="ck_project_model_assignment_platform"),
        CheckConstraint("parameter_revision >= 0", name="ck_project_model_assignment_parameter_revision"),
        Index("ix_project_model_assignments_project_enabled", "project_id", "enabled"),
    )


class ProjectSceneRecord(Base):
    __tablename__ = "project_scenes"

    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_types: Mapped[list] = mapped_column(JsonDocument, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deletion_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_account_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (CheckConstraint("revision >= 1", name="ck_project_scene_revision"),)


class ResourceLifecycleOperationRecord(Base):
    """Durable request identity and recoverable cross-storage intent, never a grant."""
    __tablename__ = "resource_lifecycle_operations"

    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    result: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResourceLifecycleEventRecord(Base):
    """Domain outbox retained until M112-T03 projects durable current truth."""
    __tablename__ = "resource_lifecycle_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    scope_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    lifecycle_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProjectSceneMemberRecord(Base):
    __tablename__ = "project_scene_members"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[str] = mapped_column(String(128), nullable=False, default="legacy-member")
    project_model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project_model_assignments.assignment_id", ondelete="RESTRICT"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str] = mapped_column(String(16), nullable=False)
    execution: Mapped[str] = mapped_column(String(16), nullable=False)
    input_types: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    parameter_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parameter_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument, nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "scene_id"], ["project_scenes.project_id", "project_scenes.scene_id"], ondelete="CASCADE", name="fk_scene_members_project_scene"),
        UniqueConstraint("project_id", "scene_id", "member_id", name="uq_scene_member_identity"),
        UniqueConstraint("project_id", "scene_id", "project_model_id", name="uq_scene_member_project_model"),
        CheckConstraint("position >= 0", name="ck_scene_member_position"),
        CheckConstraint("target IN ('pc', 'mobile')", name="ck_scene_member_target"),
        CheckConstraint("execution IN ('single', 'sync', 'async')", name="ck_scene_member_execution"),
        CheckConstraint("parameter_revision >= 0", name="ck_scene_member_parameter_revision"),
    )


class ProjectScenePlanRecord(Base):
    __tablename__ = "project_scene_plans"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_types: Mapped[list] = mapped_column(JsonDocument, nullable=False)
    execution: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    parameter_sources: Mapped[list | None] = mapped_column(JsonDocument, nullable=True)
    camera_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "scene_id"], ["project_scenes.project_id", "project_scenes.scene_id"], ondelete="CASCADE", name="fk_scene_plans_project_scene"),
        CheckConstraint("execution IN ('single', 'sync', 'async')", name="ck_scene_plan_execution"),
    )


class ProjectScenePlanMemberRecord(Base):
    __tablename__ = "project_scene_plan_members"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    member_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "scene_id", "plan_id"], ["project_scene_plans.project_id", "project_scene_plans.scene_id", "project_scene_plans.plan_id"], ondelete="CASCADE", name="fk_scene_plan_members_plan"),
        ForeignKeyConstraint(["project_id", "scene_id", "member_id"], ["project_scene_members.project_id", "project_scene_members.scene_id", "project_scene_members.member_id"], ondelete="CASCADE", name="fk_scene_plan_members_member"),
        UniqueConstraint("project_id", "scene_id", "plan_id", "position", name="uq_scene_plan_member_position"),
        CheckConstraint("position >= 0", name="ck_scene_plan_member_position"),
    )


class ProjectSceneInstallationRecord(Base):
    """Account-scoped installation preparation; never a runtime grant."""

    __tablename__ = "project_scene_installations"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target: Mapped[str] = mapped_column(String(16), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    selection_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    plan_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    member_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    required_member_ids: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    ready_member_ids: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_installed")
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["project_id", "scene_id"], ["project_scenes.project_id", "project_scenes.scene_id"], ondelete="CASCADE", name="fk_scene_installations_project_scene"),
        ForeignKeyConstraint(["account_id"], ["accounts.account_id"], ondelete="CASCADE", name="fk_scene_installations_account"),
        CheckConstraint("target IN ('pc', 'mobile')", name="ck_scene_installations_target"),
        CheckConstraint("status IN ('not_installed', 'preparing', 'partial', 'ready', 'stale', 'failed', 'blocked')", name="ck_scene_installations_status"),
    )


class ProjectSceneRuntimeGrantRecord(Base):
    """Digest-only, short-lived bearer leases bound to an approved plan snapshot."""

    __tablename__ = "project_scene_runtime_grants"

    grant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scene_id: Mapped[str] = mapped_column(String(128), nullable=False)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False)
    scene_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    member_id: Mapped[str] = mapped_column(String(128), nullable=False)
    input_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target: Mapped[str] = mapped_column(String(16), nullable=False)
    client_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    supported_execution_modes: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="single")
    member_snapshot: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    authority_snapshot: Mapped[dict] = mapped_column(JsonDocument, nullable=False, default=dict)
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["project_id", "scene_id"],
            ["project_scenes.project_id", "project_scenes.scene_id"], ondelete="CASCADE",
            name="fk_scene_runtime_grants_project_scene"),
        CheckConstraint("scene_revision >= 1", name="ck_scene_runtime_grant_revision"),
        CheckConstraint("input_type IN ('image', 'video')", name="ck_scene_runtime_grant_input"),
        CheckConstraint("target IN ('pc', 'mobile')", name="ck_scene_runtime_grant_target"),
        CheckConstraint("parameter_revision >= 0", name="ck_scene_runtime_grant_parameter_revision"),
        Index("ix_scene_runtime_grants_scope_expiry", "project_id", "scene_id", "account_id", "expires_at"),
        Index("uq_scene_runtime_grant_request", "request_digest", unique=True),
    )


class ServicePrincipalRecord(Base):
    __tablename__ = "service_principals"

    principal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    capabilities: Mapped[list] = mapped_column(JsonDocument, nullable=False)
    credential_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("project_id", "principal_id", name="uq_service_principals_project_id"),
        CheckConstraint("principal_type IN ('DEVICE', 'SERVICE')", name="ck_service_principals_type"),
        CheckConstraint("revision >= 1", name="ck_service_principals_revision"),
    )


class ServiceRequestNonceRecord(Base):
    __tablename__ = "service_request_nonces"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    nonce_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    __table_args__ = (ForeignKeyConstraint(
        ["project_id", "principal_id"], ["service_principals.project_id", "service_principals.principal_id"],
        ondelete="CASCADE", name="fk_service_nonce_project_principal",
    ),)


class ProjectAuditEventRecord(Base):
    __tablename__ = "project_audit_events"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    actor_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.account_id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_service_principal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    platform_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    previous_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_summary: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False, default=dict)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint("outcome IN ('SUCCESS', 'DENIED', 'FAILED')", name="ck_project_audit_events_outcome"),
        Index("ix_project_audit_events_project_time", "project_id", "occurred_at"),
        Index("ix_project_audit_page", "project_id", "occurred_at", "audit_id"),
        Index("ix_project_audit_page_sqlite", "project_id", func.julianday(occurred_at), "audit_id").ddl_if(dialect="sqlite"),
        Index("ix_project_audit_events_target", "project_id", "target_type", "target_id"),
    )


class PlatformAuditEventRecord(Base):
    __tablename__ = "platform_audit_events"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    actor_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.account_id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    previous_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_summary: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False, default=dict)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint("outcome IN ('SUCCESS', 'DENIED', 'FAILED')", name="ck_platform_audit_events_outcome"),
        Index("ix_platform_audit_events_target", "target_type", "target_id"),
        Index("ix_platform_audit_page", "occurred_at", "audit_id"),
        Index("ix_platform_audit_page_sqlite", func.julianday(occurred_at), "audit_id").ddl_if(dialect="sqlite"),
    )


class ConversionConfigRecord(Base):
    __tablename__ = "conversion_config"

    config_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ConversionJobRecord(Base):
    __tablename__ = "conversion_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    created_epoch: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    updated_epoch: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CalibrationDatasetRecord(Base):
    __tablename__ = "calibration_datasets"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    scenario: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    yaml_path: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_calibration_dataset_name_version"),
    )


class StreamConfigRecord(Base):
    __tablename__ = "stream_configs"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True,
        default=DEFAULT_PROJECT_ID, index=True
    )
    stream_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scene_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yolo_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    max_fps: Mapped[float] = mapped_column(Float, nullable=False)
    overlay_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("project_id", "stream_id", name="uq_stream_configs_project_stream"),
        Index("ix_stream_configs_project_enabled", "project_id", "enabled"),
    )


class DatabaseManager:
    """Lazy SQLAlchemy connection boundary; an omitted URL means explicit memory fallback."""

    def __init__(self, url: str | None, *, connect_timeout_seconds: int = 5):
        self.url = url.strip() if url else None
        self.connect_timeout_seconds = max(1, int(connect_timeout_seconds))
        self._engine: Engine | None = None
        self._sessions: sessionmaker[Session] | None = None

    @property
    def enabled(self) -> bool:
        return self.url is not None

    @property
    def backend(self) -> str:
        return make_url(self.url).get_backend_name() if self.url else "memory"

    @property
    def engine(self) -> Engine:
        if not self.url:
            raise RuntimeError("DATABASE_URL is not configured")
        if self._engine is None:
            connect_args = {}
            if self.backend == "postgresql":
                connect_args["connect_timeout"] = self.connect_timeout_seconds
            self._engine = create_engine(self.url, pool_pre_ping=True, connect_args=connect_args)
            if self.backend == "sqlite":
                # Earlier Alembic revisions persisted literal now() defaults.
                # SQLite has CURRENT_TIMESTAMP but no built-in now() function.
                @event.listens_for(self._engine, "connect")
                def _sqlite_legacy_now(connection, _record):
                    connection.create_function(
                        "now", 0, lambda: datetime.now(timezone.utc).isoformat(sep=" ")
                    )
            self._sessions = sessionmaker(bind=self._engine, expire_on_commit=False)
        return self._engine

    def connect(self) -> dict[str, Any]:
        if not self.enabled:
            return {"configured": False, "backend": "memory", "status": "fallback"}
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"configured": True, "backend": self.backend, "status": "ok"}

    def verify_schema(self) -> dict[str, Any]:
        state = self.connect()
        if not self.enabled:
            return state
        required = {
            "service_principals", "service_request_nonces",
            "accounts", "account_sessions", "projects", "project_memberships",
            "project_model_assignments", "project_scenes", "project_scene_members",
            "project_scene_plans", "project_scene_plan_members", "project_scene_installations",
            "project_scene_runtime_grants",
            "resource_lifecycle_operations", "resource_lifecycle_events",
            "project_audit_events", "platform_audit_events",
            "alert_events", "alert_disposition_actions", "false_positive_feedback",
            "alert_rules", "alert_rule_bindings", "alert_rule_audits",
            "model_parameter_profiles", "model_parameter_audits",
            "alert_verification_config", "alert_verifications", "alert_delivery_receipts",
            "alert_advice_knowledge_entries", "alert_advice_knowledge_revisions",
            "alert_advice_generations",
            "system_knowledge_catalog", "system_knowledge_releases", "project_knowledge_bases",
            "conversion_config", "conversion_jobs", "calibration_datasets",
            "stream_configs", "project_business_config", "alembic_version",
        }
        available = set(inspect(self.engine).get_table_names())
        from .model_updates.models import TABLES
        required.update(model.__tablename__ for model in TABLES)
        from .app_updates.models import TABLES as APP_UPDATE_TABLES
        required.update(model.__tablename__ for model in APP_UPDATE_TABLES)
        missing = sorted(required - available)
        if missing:
            raise RuntimeError(
                "database schema is not initialized; run 'python -m alembic upgrade head' "
                f"(missing: {', '.join(missing)})"
            )
        if "parameter_snapshot" not in {column["name"] for column in
                                        inspect(self.engine).get_columns("project_scene_members")}:
            raise RuntimeError("scene parameter schema is not initialized; run 'python -m alembic upgrade head'")
        scene_member_columns = {column["name"] for column in inspect(self.engine).get_columns("project_scene_members")}
        if not {"deleted_at", "deletion_operation_id"}.issubset(
                {column["name"] for column in inspect(self.engine).get_columns("project_scenes")}):
            raise RuntimeError("resource lifecycle schema is not initialized; run 'python -m alembic upgrade head'")
        if not {"member_id", "input_types", "project_model_id", "parameter_revision"}.issubset(scene_member_columns):
            raise RuntimeError("scene suite schema is not initialized; run 'python -m alembic upgrade head'")
        grant_columns = {column["name"] for column in inspect(self.engine).get_columns("project_scene_runtime_grants")}
        if not {"execution_mode", "member_snapshot", "authority_snapshot", "request_digest"}.issubset(grant_columns):
            raise RuntimeError("composite runtime grant schema is not initialized; run 'python -m alembic upgrade head'")
        return {**state, "schema": "ready"}

    def health(self) -> dict[str, Any]:
        try:
            return self.verify_schema()
        except Exception as exc:
            return {
                "configured": self.enabled,
                "backend": self.backend,
                "status": "unavailable",
                "error": exc.__class__.__name__,
            }

    @contextmanager
    def session(self) -> Iterator[Session]:
        self.engine
        assert self._sessions is not None
        session = self._sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._sessions = None


from .config import settings


database = DatabaseManager(
    settings.database_url,
    connect_timeout_seconds=settings.database_connect_timeout_seconds,
)

# Register all mapped tables for direct Base.metadata test/setup consumers too.
from .model_updates import models as _model_update_models
from .app_updates import models as _app_update_models
