"""M111 persistence. Sequence allocation is protected by the binding row lock."""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base, JsonDocument


class Installation(Base):
    __tablename__ = 'model_update_installations'
    installation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    device_id: Mapped[str | None] = mapped_column(String(128))


class Device(Base):
    __tablename__ = 'model_update_devices'
    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    installation_id: Mapped[str] = mapped_column(ForeignKey(Installation.installation_id), nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(256), nullable=False)
    epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capabilities: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    push_provider: Mapped[str] = mapped_column(String(16), nullable=False)
    push_token: Mapped[str | None] = mapped_column(String(4096))
    token_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    notification_permission: Mapped[str] = mapped_column(String(32), nullable=False)
    inventory_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    inventory_digest: Mapped[str | None] = mapped_column(String(64))
    inventory: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    source_epochs: Mapped[dict] = mapped_column(JsonDocument, nullable=False, default=dict)
    lifecycle_facts: Mapped[dict] = mapped_column(JsonDocument, nullable=False, default=dict)
    lifecycle_inventory: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cursor_floor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_contact: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint('installation_id', 'epoch'),)


class Target(Base):
    __tablename__ = 'model_update_targets'
    update_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JsonDocument, nullable=False)


class Inbox(Base):
    __tablename__ = 'model_update_inbox'
    device_id: Mapped[str] = mapped_column(ForeignKey(Device.device_id), primary_key=True)
    update_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(512), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    payload: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    report_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    authority_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Change(Base):
    __tablename__ = 'model_update_changes'
    device_id: Mapped[str] = mapped_column(ForeignKey(Device.device_id), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    update_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Receipt(Base):
    __tablename__ = 'model_update_reports'
    device_id: Mapped[str] = mapped_column(ForeignKey(Device.device_id), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    update_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    result: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Ticket(Base):
    __tablename__ = 'model_update_tickets'
    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey(Device.device_id), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class Snapshot(Base):
    __tablename__ = 'model_update_snapshots'
    snapshot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey(Device.device_id), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[list] = mapped_column(JsonDocument, nullable=False)
    lifecycle_payload: Mapped[dict | list] = mapped_column(JsonDocument, nullable=False, default=list)
    cursor: Mapped[str] = mapped_column(String(2048), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class PushOutbox(Base):
    __tablename__ = 'model_update_push_outbox'
    device_id: Mapped[str] = mapped_column(ForeignKey(Device.device_id), primary_key=True)
    dirty_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sent_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_id: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled_reason: Mapped[str | None] = mapped_column(String(64))
    dirty_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DomainEvent(Base):
    __tablename__ = 'model_update_domain_outbox'
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RateBucket(Base):
    __tablename__ = 'model_update_rate_buckets'
    bucket_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)


class Metric(Base):
    __tablename__ = 'model_update_metrics'
    metric_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    maximum: Mapped[float] = mapped_column(Float, nullable=False, default=0)


TABLES = (Installation, Device, Target, Inbox, Change, Receipt, Ticket, Snapshot, PushOutbox, DomainEvent, RateBucket, Metric)
