"""App upgrade records. Never share model-update tables or project grants.

Cross-row publish/readiness/CAS and immutable-after-verification rules belong
to the transactional service (M42-T05/T08); constraints here guard row identity,
history retention, scoped references, version reuse and idempotency.
"""
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base, JsonDocument, _new_id


class Created:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AppIdentity(Created, Base):
    __tablename__ = "app_update_identities"
    package_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    publisher_id: Mapped[str] = mapped_column(String(128), nullable=False)
    first_version_code: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    version_high_water: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # No signing private key, metadata key, or auto-approved debug certificate.
    approved_signer_sha256: Mapped[str | None] = mapped_column(String(64))
    metadata_key_config_ref: Mapped[str | None] = mapped_column(String(255))
    __table_args__ = (
        UniqueConstraint("package_name", "publisher_id", name="uq_app_identity_publisher"),
        CheckConstraint("package_name = 'com.aiyolo.inspection'", name="ck_app_identity_package"),
        CheckConstraint("first_version_code = 1 AND version_high_water BETWEEN 0 AND 2147483647", name="ck_app_identity_version"),
        CheckConstraint("approved_signer_sha256 IS NULL OR length(approved_signer_sha256) = 64", name="ck_app_identity_signer"),
    )


class AppArtifact(Created, Base):
    __tablename__ = "app_artifacts"
    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True, default=_new_id)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    publisher_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    version_code: Mapped[int | None] = mapped_column(BigInteger)
    version_name: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    signer_sha256: Mapped[str | None] = mapped_column(String(64))
    min_sdk: Mapped[int | None] = mapped_column(Integer)
    abis: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    server_contract_min: Mapped[int | None] = mapped_column(Integer)
    server_contract_max: Mapped[int | None] = mapped_column(Integer)
    data_schema_version: Mapped[int | None] = mapped_column(Integer)
    readable_schema_min: Mapped[int | None] = mapped_column(Integer)
    readable_schema_max: Mapped[int | None] = mapped_column(Integer)
    verification_evidence_ref: Mapped[str | None] = mapped_column(String(512))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    build_provenance: Mapped[dict] = mapped_column(JsonDocument, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["package_name", "publisher_id"], ["app_update_identities.package_name", "app_update_identities.publisher_id"], ondelete="RESTRICT"),
        UniqueConstraint("package_name", "version_code", name="uq_app_artifact_global_version"),
        UniqueConstraint("artifact_id", "package_name", "publisher_id", name="uq_app_artifact_identity"),
        CheckConstraint("state IN ('pending', 'verifying', 'verified', 'failed')", name="ck_app_artifact_state"),
        CheckConstraint("version_code IS NULL OR version_code BETWEEN 1 AND 2147483647", name="ck_app_artifact_version"),
        CheckConstraint("size_bytes IS NULL OR size_bytes BETWEEN 1 AND 8589934592", name="ck_app_artifact_size"),
        CheckConstraint("sha256 IS NULL OR length(sha256) = 64", name="ck_app_artifact_hash"),
        CheckConstraint("signer_sha256 IS NULL OR length(signer_sha256) = 64", name="ck_app_artifact_signer"),
        CheckConstraint("min_sdk IS NULL OR min_sdk >= 27", name="ck_app_artifact_sdk"),
        CheckConstraint("server_contract_min IS NULL OR (server_contract_min >= 1 AND server_contract_max >= server_contract_min)", name="ck_app_artifact_contract"),
        CheckConstraint("data_schema_version IS NULL OR (readable_schema_min >= 1 AND readable_schema_min <= data_schema_version AND readable_schema_max >= data_schema_version)", name="ck_app_artifact_data_schema"),
        CheckConstraint("state != 'verified' OR (version_code IS NOT NULL AND version_name IS NOT NULL AND size_bytes IS NOT NULL AND sha256 IS NOT NULL AND signer_sha256 IS NOT NULL AND min_sdk IS NOT NULL AND server_contract_min IS NOT NULL AND server_contract_max IS NOT NULL AND data_schema_version IS NOT NULL AND readable_schema_min IS NOT NULL AND readable_schema_max IS NOT NULL AND verification_evidence_ref IS NOT NULL AND verified_at IS NOT NULL)", name="ck_app_artifact_verified_evidence"),
        Index("ix_app_artifact_state_created", "state", "created_at"),
    )


class AppArtifactSource(Created, Base):
    __tablename__ = "app_artifact_sources"
    source_id: Mapped[str] = mapped_column(String(128), primary_key=True, default=_new_id)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("app_artifacts.artifact_id", ondelete="RESTRICT"), nullable=False)
    source_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    access_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    public_url: Mapped[str | None] = mapped_column(Text)
    bucket: Mapped[str | None] = mapped_column(String(255))
    object_key: Mapped[str | None] = mapped_column(String(1024))
    object_version_id: Mapped[str | None] = mapped_column(String(255))
    object_etag: Mapped[str | None] = mapped_column(String(255))
    credential_config_ref: Mapped[str | None] = mapped_column(String(255))
    allowed_hosts: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    verified_sha256: Mapped[str | None] = mapped_column(String(64))
    verified_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_evidence_ref: Mapped[str | None] = mapped_column(String(512))
    availability_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        UniqueConstraint("artifact_id", "source_revision", name="uq_app_source_revision"),
        UniqueConstraint("source_id", "artifact_id", "source_revision", name="uq_app_source_binding"),
        CheckConstraint("source_revision BETWEEN 1 AND 2147483647", name="ck_app_source_revision"),
        CheckConstraint("state IN ('pending', 'verifying', 'verified', 'failed', 'retired')", name="ck_app_source_state"),
        CheckConstraint("availability_state IN ('unknown', 'available', 'unavailable')", name="ck_app_source_availability"),
        CheckConstraint("(storage_mode = 'external' AND access_mode = 'public' AND public_url LIKE 'https://%' AND public_url IS NOT NULL AND bucket IS NULL AND object_key IS NULL AND credential_config_ref IS NULL) OR (storage_mode = 'internal' AND access_mode IN ('public', 'presigned') AND bucket IS NOT NULL AND object_key IS NOT NULL AND public_url IS NULL)", name="ck_app_source_location"),
        CheckConstraint("state != 'verified' OR (verified_sha256 IS NOT NULL AND length(verified_sha256) = 64 AND verified_size_bytes BETWEEN 1 AND 8589934592 AND verified_size_bytes IS NOT NULL AND verified_at IS NOT NULL AND verification_evidence_ref IS NOT NULL)", name="ck_app_source_verified_evidence"),
        Index("ix_app_source_artifact_state", "artifact_id", "state"),
    )


class AppPolicy(Created, Base):
    __tablename__ = "app_update_policies"
    policy_id: Mapped[str] = mapped_column(String(128), primary_key=True, default=_new_id)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    publisher_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(128), nullable=False)
    deployment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    min_supported_version_code: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    restricted_capabilities: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    # Contains immutable release/source IDs, stopped IDs and recovery bindings.
    # This is the active selection snapshot, not a per-device signed response.
    selection: Mapped[dict] = mapped_column(JsonDocument, nullable=False, default=dict)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["package_name", "publisher_id"], ["app_update_identities.package_name", "app_update_identities.publisher_id"], ondelete="RESTRICT"),
        UniqueConstraint("publisher_id", "package_name", "channel", "deployment_id", name="uq_app_policy_scope"),
        UniqueConstraint("policy_id", "package_name", "publisher_id", name="uq_app_policy_identity"),
        CheckConstraint("revision BETWEEN 1 AND 2147483647", name="ck_app_policy_revision"),
        CheckConstraint("min_supported_version_code BETWEEN 1 AND 2147483647", name="ck_app_policy_floor"),
    )


class AppRelease(Created, Base):
    __tablename__ = "app_releases"
    release_id: Mapped[str] = mapped_column(String(128), primary_key=True, default=_new_id)
    policy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    publisher_id: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    importance: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    notes: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list)
    recovery_evidence_ref: Mapped[str | None] = mapped_column(String(512))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["policy_id", "package_name", "publisher_id"], ["app_update_policies.policy_id", "app_update_policies.package_name", "app_update_policies.publisher_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["artifact_id", "package_name", "publisher_id"], ["app_artifacts.artifact_id", "app_artifacts.package_name", "app_artifacts.publisher_id"], ondelete="RESTRICT"),
        UniqueConstraint("policy_id", "release_id", name="uq_app_release_scope"),
        UniqueConstraint("policy_id", "release_id", "artifact_id", name="uq_app_release_artifact"),
        UniqueConstraint("policy_id", "artifact_id", name="uq_app_release_policy_artifact"),
        CheckConstraint("state IN ('draft', 'published', 'stopped')", name="ck_app_release_state"),
        CheckConstraint("importance IN ('normal', 'important')", name="ck_app_release_importance"),
        CheckConstraint("purpose IN ('normal', 'recovery')", name="ck_app_release_purpose"),
        CheckConstraint("state != 'published' OR (published_at IS NOT NULL AND (purpose != 'recovery' OR recovery_evidence_ref IS NOT NULL))", name="ck_app_release_published"),
        CheckConstraint("state != 'stopped' OR stopped_at IS NOT NULL", name="ck_app_release_stopped"),
        Index("ix_app_release_policy_state", "policy_id", "state"),
    )


class AppPolicyRevision(Created, Base):
    __tablename__ = "app_update_policy_revisions"
    policy_id: Mapped[str] = mapped_column(ForeignKey("app_update_policies.policy_id", ondelete="RESTRICT"), primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_base64url: Mapped[str] = mapped_column(Text, nullable=False)
    signature_base64url: Mapped[str] = mapped_column(String(86), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        CheckConstraint("revision BETWEEN 1 AND 2147483647", name="ck_app_policy_history_revision"),
        CheckConstraint("length(snapshot_sha256) = 64 AND length(signature_base64url) = 86", name="ck_app_policy_history_signature"),
    )


class AppRollback(Created, Base):
    __tablename__ = "app_rollback_operations"
    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True, default=_new_id)
    policy_id: Mapped[str] = mapped_column(ForeignKey("app_update_policies.policy_id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_policy_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_policy_revision: Mapped[int | None] = mapped_column(BigInteger)
    affected_release_ids: Mapped[list] = mapped_column(JsonDocument, nullable=False)
    stable_release_id: Mapped[str] = mapped_column(String(128), nullable=False)
    recovery_release_id: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    recovery_state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    recovery_evidence_ref: Mapped[str | None] = mapped_column(String(512))
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(["policy_id", "stable_release_id"], ["app_releases.policy_id", "app_releases.release_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["policy_id", "recovery_release_id"], ["app_releases.policy_id", "app_releases.release_id"], ondelete="RESTRICT"),
        UniqueConstraint("policy_id", "idempotency_key", name="uq_app_rollback_idempotency"),
        CheckConstraint("state IN ('accepted', 'applied', 'failed') AND recovery_state IN ('ready', 'pending')", name="ck_app_rollback_state"),
        CheckConstraint("expected_policy_revision BETWEEN 1 AND 2147483647 AND (effective_policy_revision IS NULL OR effective_policy_revision > expected_policy_revision)", name="ck_app_rollback_revision"),
        CheckConstraint("state != 'applied' OR (effective_policy_revision IS NOT NULL AND applied_at IS NOT NULL)", name="ck_app_rollback_applied"),
        CheckConstraint("recovery_state != 'ready' OR (recovery_release_id IS NOT NULL AND recovery_evidence_ref IS NOT NULL)", name="ck_app_rollback_recovery"),
        CheckConstraint("length(request_sha256) = 64 AND length(preview_fingerprint) = 64 AND length(reason) > 0", name="ck_app_rollback_request"),
        Index("ix_app_rollback_policy_created", "policy_id", "created_at"),
    )


class AppDeviceState(Base):
    __tablename__ = "app_update_device_states"
    policy_id: Mapped[str] = mapped_column(ForeignKey("app_update_policies.policy_id", ondelete="RESTRICT"), primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    current_version_code: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_policy_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    attempt_id: Mapped[str | None] = mapped_column(String(128))
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="not_discovered")
    observed: Mapped[dict] = mapped_column(JsonDocument, nullable=False, default=dict)
    last_contact_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("current_version_code BETWEEN 1 AND 2147483647 AND last_policy_revision >= 0 AND last_sequence >= 0", name="ck_app_device_version"),
        CheckConstraint("stage IN ('not_discovered', 'discovered', 'downloading', 'downloaded', 'verified', 'waiting_install', 'installer_opened', 'started_pending_health', 'healthy', 'failed', 'canceled', 'superseded')", name="ck_app_device_stage"),
        Index("ix_app_device_policy_contact", "policy_id", "last_contact_at"),
    )


class AppReceipt(Created, Base):
    __tablename__ = "app_update_receipts"
    policy_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    release_id: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(128))
    source_revision: Mapped[int | None] = mapped_column(BigInteger)
    policy_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    from_version_code: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_version_code: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_version_code: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        ForeignKeyConstraint(["policy_id", "installation_id"], ["app_update_device_states.policy_id", "app_update_device_states.installation_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["policy_id", "release_id", "artifact_id"], ["app_releases.policy_id", "app_releases.release_id", "app_releases.artifact_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["source_id", "artifact_id", "source_revision"], ["app_artifact_sources.source_id", "app_artifact_sources.artifact_id", "app_artifact_sources.source_revision"], ondelete="RESTRICT"),
        UniqueConstraint("policy_id", "installation_id", "attempt_id", "sequence", name="uq_app_receipt_sequence"),
        CheckConstraint("(source_id IS NULL AND source_revision IS NULL) OR (source_id IS NOT NULL AND source_revision IS NOT NULL AND source_revision >= 1)", name="ck_app_receipt_source"),
        CheckConstraint("sequence >= 1 AND policy_revision >= 1 AND length(request_sha256) = 64", name="ck_app_receipt_revision"),
        CheckConstraint("from_version_code >= 1 AND target_version_code > from_version_code AND target_version_code <= 2147483647 AND observed_version_code BETWEEN 1 AND 2147483647", name="ck_app_receipt_version"),
        CheckConstraint("stage IN ('discovered', 'downloading', 'downloaded', 'verified', 'waiting_install', 'installer_opened', 'started_pending_health', 'healthy', 'failed', 'canceled', 'superseded')", name="ck_app_receipt_stage"),
        CheckConstraint("stage NOT IN ('started_pending_health', 'healthy') OR observed_version_code = target_version_code", name="ck_app_receipt_health"),
        CheckConstraint("stage != 'failed' OR error_code IS NOT NULL", name="ck_app_receipt_failure"),
        CheckConstraint("stage != 'superseded' OR observed_version_code > target_version_code", name="ck_app_receipt_superseded"),
        Index("ix_app_receipt_release_stage", "policy_id", "release_id", "stage"),
    )


class AppAudit(Created, Base):
    __tablename__ = "app_update_audit_events"
    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True, default=_new_id)
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("app_update_policies.policy_id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    before_revision: Mapped[int | None] = mapped_column(BigInteger)
    after_revision: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    # Only allowlisted IDs, hashes, error codes; no raw URLs or request bodies.
    details: Mapped[dict] = mapped_column(JsonDocument, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("actor_id", "action", "idempotency_key", name="uq_app_audit_idempotency"),
        CheckConstraint("result IN ('accepted', 'succeeded', 'rejected', 'failed') AND length(request_sha256) = 64 AND length(reason) > 0", name="ck_app_audit_result"),
        Index("ix_app_audit_resource_created", "resource_id", "created_at"),
    )


class AppUpload(Created, Base):
    __tablename__ = "app_apk_uploads"
    upload_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    artifact_id: Mapped[str] = mapped_column(ForeignKey("app_artifacts.artifact_id", ondelete="RESTRICT"), nullable=False)
    resolved_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("app_artifacts.artifact_id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    compatibility: Mapped[dict] = mapped_column(JsonDocument, nullable=False, default=dict)
    reason: Mapped[str | None] = mapped_column(String(1000))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    cleanup_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="upload", server_default="upload")
    external_url: Mapped[str | None] = mapped_column(Text)
    external_hosts: Mapped[list] = mapped_column(JsonDocument, nullable=False, default=list, server_default="[]")
    fetch_evidence: Mapped[dict] = mapped_column(JsonDocument, nullable=False, default=dict, server_default="{}")
    target_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("app_artifacts.artifact_id", ondelete="RESTRICT"))
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", name="uq_app_upload_idempotency"),
        CheckConstraint("state IN ('receiving', 'queued', 'processing', 'retryable', 'succeeded', 'failed')", name="ck_app_upload_state"),
        CheckConstraint("attempts >= 0 AND (size_bytes IS NULL OR size_bytes BETWEEN 1 AND 8589934592)", name="ck_app_upload_size"),
        CheckConstraint("kind IN ('upload', 'external') AND (kind != 'external' OR external_url IS NOT NULL)", name="ck_app_upload_kind"),
        Index("ix_app_upload_state_lease", "state", "lease_until"),
    )


TABLES = (AppIdentity, AppArtifact, AppArtifactSource, AppPolicy, AppRelease,
          AppPolicyRevision, AppRollback, AppDeviceState, AppReceipt, AppAudit, AppUpload)
