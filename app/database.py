from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, create_engine, func, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


JsonDocument = JSON().with_variant(JSONB, "postgresql")
RecordId = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass


class AccountRecord(Base):
    __tablename__ = "accounts"

    username: Mapped[str] = mapped_column(String(128), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AccountSessionRecord(Base):
    __tablename__ = "account_sessions"

    session_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(
        String(128), ForeignKey("accounts.username", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AlertEventRecord(Base):
    __tablename__ = "alert_events"

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

    __table_args__ = (Index("ix_alert_events_updated_at", "updated_at"),)


class AlertDispositionActionRecord(Base):
    __tablename__ = "alert_disposition_actions"

    id: Mapped[int] = mapped_column(RecordId, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("alert_events.event_id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    acted_at_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("event_id", "status", "actor", "acted_at_us", name="uq_alert_disposition_action"),
    )


class FalsePositiveFeedbackRecord(Base):
    __tablename__ = "false_positive_feedback"

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("alert_events.event_id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_id: Mapped[int] = mapped_column(
        RecordId, ForeignKey("alert_disposition_actions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AlertRuleRecord(Base):
    __tablename__ = "alert_rules"

    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AlertRuleBindingRecord(Base):
    __tablename__ = "alert_rule_bindings"

    rule_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("alert_rules.rule_id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AlertRuleAuditRecord(Base):
    __tablename__ = "alert_rule_audits"

    id: Mapped[int] = mapped_column(RecordId, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelParameterProfileRecord(Base):
    __tablename__ = "model_parameter_profiles"

    profile_key: Mapped[str] = mapped_column(String(512), primary_key=True)
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
        UniqueConstraint("model_id", "model_version", "platform", name="uq_model_parameter_profile"),
    )


class ModelParameterAuditRecord(Base):
    __tablename__ = "model_parameter_audits"

    id: Mapped[int] = mapped_column(RecordId, primary_key=True, autoincrement=True)
    profile_key: Mapped[str] = mapped_column(
        String(512), ForeignKey("model_parameter_profiles.profile_key", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AlertVerificationConfigRecord(Base):
    __tablename__ = "alert_verification_config"

    config_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    calls_day: Mapped[int] = mapped_column(Integer, nullable=False)
    calls_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AlertVerificationRecord(Base):
    __tablename__ = "alert_verifications"

    event_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("alert_events.event_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AlertDeliveryReceiptRecord(Base):
    __tablename__ = "alert_delivery_receipts"

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

    stream_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
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
            "accounts", "account_sessions",
            "alert_events", "alert_disposition_actions", "false_positive_feedback",
            "alert_rules", "alert_rule_bindings", "alert_rule_audits",
            "model_parameter_profiles", "model_parameter_audits",
            "alert_verification_config", "alert_verifications", "alert_delivery_receipts",
            "conversion_config", "conversion_jobs", "calibration_datasets",
            "stream_configs", "alembic_version",
        }
        available = set(inspect(self.engine).get_table_names())
        missing = sorted(required - available)
        if missing:
            raise RuntimeError(
                "database schema is not initialized; run 'python -m alembic upgrade head' "
                f"(missing: {', '.join(missing)})"
            )
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
