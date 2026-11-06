"""Durable bounded staging, idempotent registration, leased verification/promotion."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import threading
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from ..database import AccountRecord
from .apk_verifier import Expectations, VerificationError
from .models import AppArtifact, AppArtifactSource, AppAudit, AppIdentity, AppUpload
from .minio_store import StorageError
from .verification_jobs import BuildCompatibility, VerificationJobs
from .security import audit_text, session_valid


class UploadError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def now():
    return datetime.now(timezone.utc)


class ApkUploads:
    kind = "upload"
    def __init__(self, database, verifier, store, *, root, compatibility, max_jobs=4, lease_seconds=1800):
        self.db, self.verifier, self.store = database, verifier, store
        self.root = Path(root).resolve()
        self.compatibility = compatibility
        self.max_jobs, self.lease_seconds = max_jobs, lease_seconds
        if not 1 <= max_jobs <= 64 or not 60 <= lease_seconds <= 7200:
            raise ValueError("invalid APK worker limits")
        self.stop_event = threading.Event()
        self.thread = None

    def authorize(self, session, actor):
        if not session_valid(session, actor):
            raise UploadError("authentication_required", 401)
        account = session.scalar(select(AccountRecord).where(AccountRecord.account_id == actor).with_for_update())
        if not account or not account.enabled or account.platform_role != "PLATFORM_ADMIN":
            raise UploadError("platform_admin_required", 403)

    def begin(self, actor):
        self.compatibility.validate()
        self.root.mkdir(parents=True, exist_ok=True)
        upload_id, artifact_id = str(uuid4()), str(uuid4())
        with self.db.session() as session:
            identity = session.execute(select(AppIdentity).with_for_update()).scalar_one_or_none()
            self.authorize(session, actor)
            if identity is None or not identity.approved_signer_sha256:
                raise UploadError("signer_not_configured", 503)
            session.execute(update(AppIdentity).where(AppIdentity.package_name == identity.package_name).values(
                version_high_water=AppIdentity.version_high_water))
            active = session.scalar(select(func.count()).select_from(AppUpload).where(or_(AppUpload.state.in_(
                ["receiving", "queued", "processing", "retryable"]), AppUpload.cleanup_pending.is_(True))))
            if active >= self.max_jobs:
                raise UploadError("apk_upload_capacity", 429)
            session.add(AppArtifact(artifact_id=artifact_id, package_name=identity.package_name,
                publisher_id=identity.publisher_id, created_by=actor))
            session.flush()
            session.add(AppUpload(upload_id=upload_id, actor_id=actor, artifact_id=artifact_id,
                state="receiving", lease_until=now() + timedelta(seconds=self.lease_seconds),
                compatibility=asdict(self.compatibility)))
        return upload_id

    def path(self, upload_id):
        # IDs come from DB or this service, never a submitted filename/path.
        if str(UUID(upload_id)) != upload_id:
            raise UploadError("invalid_upload_id", 422)
        return self.root / (upload_id + ".apk")

    def finish(self, upload_id, *, idempotency_key, reason, size_bytes, sha256, actor=None):
        request_hash = hashlib.sha256(json.dumps([sha256, size_bytes, reason, asdict(self.compatibility)],
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        duplicate = None
        if not 1 <= len(idempotency_key) <= 128 or not reason.strip() or len(reason) > 1000 or size_bytes < 1:
            raise UploadError("invalid_upload_fields", 422)
        try:
            with self.db.session() as session:
                identity = session.execute(select(AppIdentity).with_for_update()).scalar_one()
                session.execute(update(AppIdentity).where(AppIdentity.package_name == identity.package_name).values(
                    version_high_water=AppIdentity.version_high_water))
                job = session.get(AppUpload, upload_id)
                if not job or job.state != "receiving":
                    raise UploadError("upload_state_conflict")
                if actor is not None and actor != job.actor_id:
                    raise UploadError("authentication_required", 401)
                self.authorize(session, actor if actor is not None else job.actor_id)
                previous = session.scalar(select(AppUpload).where(AppUpload.actor_id == job.actor_id,
                    AppUpload.idempotency_key == idempotency_key))
                if previous:
                    if previous.kind != self.kind or previous.request_sha256 != request_hash:
                        raise UploadError("idempotency_conflict")
                    duplicate = previous.upload_id
                    job.state, job.cleanup_pending = "failed", True
                    job.error_code = "duplicate_upload"
                    artifact = session.get(AppArtifact, job.artifact_id)
                    artifact.state, artifact.error_code = "failed", "duplicate_upload"
                    self.audit(session, job, "rejected")
                else:
                    job.idempotency_key, job.reason = idempotency_key, audit_text(reason)
                    job.size_bytes, job.sha256, job.request_sha256 = size_bytes, sha256, request_hash
                    job.state = "queued"
                    self.audit(session, job, "accepted")
        except IntegrityError as exc:
            self.fail_receive(upload_id, "idempotency_conflict")
            raise UploadError("idempotency_conflict") from exc
        if duplicate:
            self.cleanup(upload_id)
        return self.status(duplicate or upload_id)

    def status(self, upload_id):
        with self.db.session() as session:
            job = session.get(AppUpload, upload_id)
            if not job:
                raise UploadError("upload_not_found", 404)
            artifact = session.get(AppArtifact, job.resolved_artifact_id or job.artifact_id)
            # ResourceResult remains frozen; internal job errors are available
            # through admin detail endpoints in T05, never leak local paths.
            state = "verified" if job.state == "succeeded" else "failed" if job.state == "failed" else "verifying" if job.state == "processing" else "pending"
            return {"resourceId": artifact.artifact_id, "state": state, "revision": 1}

    def fail_receive(self, upload_id, code):
        clean = False
        with self.db.session() as session:
            job = session.get(AppUpload, upload_id)
            if job and job.state == "receiving":
                job.state, job.error_code, job.cleanup_pending = "failed", code, True
                self.audit(session, job, "failed")
                artifact = session.get(AppArtifact, job.artifact_id)
                artifact.state, artifact.error_code = "failed", code
                clean = True
        if clean:
            self.cleanup(upload_id)

    def cleanup(self, upload_id):
        with self.db.session() as session:
            job = session.scalar(select(AppUpload).where(AppUpload.upload_id == upload_id).with_for_update())
            if not job or job.state not in ("failed", "succeeded"):
                return False
            try:
                self.path(upload_id).unlink(missing_ok=True)
            except OSError:
                job.cleanup_pending = True
                return False
            job.cleanup_pending = False
        return True

    def recover(self):
        with self.db.session() as session:
            # Same lock order as verification/finalization. Fences any old
            # worker before resetting its artifact for another attempt.
            session.execute(select(AppIdentity).with_for_update()).all()
            expired = session.scalars(select(AppUpload).where(AppUpload.lease_until < now(),
                AppUpload.kind == self.kind,
                AppUpload.state.in_(["receiving", "processing"])).with_for_update(skip_locked=True)).all()
            for job in expired:
                if job.state == "receiving":
                    job.state, job.error_code, job.cleanup_pending = "failed", "upload_interrupted", True
                else:
                    job.state, job.lease_token = "retryable", None
                    artifact = session.get(AppArtifact, job.artifact_id)
                    if artifact.state == "verifying":
                        artifact.state = "failed"
                        artifact.error_code = "verification_interrupted"
                self.audit(session, job, "failed")
            cleanup = session.scalars(select(AppUpload.upload_id).where(AppUpload.cleanup_pending.is_(True),
                AppUpload.kind == self.kind,
                AppUpload.state.in_(["failed", "succeeded"]))).all()
        for upload_id in cleanup:
            self.cleanup(upload_id)

    def process_one(self):
        token = str(uuid4())
        with self.db.session() as session:
            eligible = or_(AppUpload.state == "queued", (AppUpload.state == "retryable") & (AppUpload.lease_until <= now()))
            job = session.scalar(select(AppUpload).where(eligible, AppUpload.kind == self.kind).order_by(AppUpload.created_at).with_for_update(skip_locked=True))
            if not job:
                return False
            upload_id, actor = job.upload_id, job.actor_id
            claimed = session.execute(update(AppUpload).where(AppUpload.upload_id == upload_id, eligible).values(
                state="processing", lease_token=token, lease_until=now() + timedelta(seconds=self.lease_seconds),
                attempts=AppUpload.attempts + 1).execution_options(synchronize_session=False)).rowcount
            if claimed != 1:
                return False
            artifact_id, size, digest = job.resolved_artifact_id or job.artifact_id, job.size_bytes, job.sha256
            compatibility = BuildCompatibility(**job.compatibility)
        def guard(session):
            current = session.scalar(select(AppUpload).where(AppUpload.upload_id == upload_id).with_for_update())
            if current.state != "processing" or current.lease_token != token:
                raise UploadError("upload_lease_lost")
            self.authorize(session, actor)
        try:
            with self.db.session() as session:
                self.authorize(session, actor)
                artifact = session.get(AppArtifact, artifact_id)
                verified = artifact.state == "verified"
                if artifact.error_code == "duplicate_existing_artifact":
                    verified = False
            if not verified:
                artifact_id = VerificationJobs(self.db, self.verifier).verify_file(artifact_id, self.path(upload_id),
                    actor_id=actor, compatibility=compatibility, expected=Expectations(size_bytes=size, sha256=digest), guard=guard)
            with self.db.session() as session:
                guard(session)
                session.get(AppUpload, upload_id).resolved_artifact_id = artifact_id
                artifact = session.get(AppArtifact, artifact_id)
                self.authorize(session, actor)
                if artifact.sha256 != digest or artifact.size_bytes != size:
                    raise UploadError("apk_staging_changed")
            stored = self.store.promote(self.path(upload_id), artifact_id=artifact_id, sha256=digest, size_bytes=size)
            with self.db.session() as session:
                identity = session.execute(select(AppIdentity).with_for_update()).scalar_one()
                guard(session)
                job = session.execute(select(AppUpload).where(AppUpload.upload_id == upload_id).with_for_update()).scalar_one()
                if job.lease_token != token or job.state != "processing":
                    raise UploadError("upload_lease_lost")
                self.authorize(session, actor)
                artifact = session.execute(select(AppArtifact).where(AppArtifact.artifact_id == artifact_id).with_for_update()).scalar_one()
                if identity.approved_signer_sha256 != artifact.signer_sha256:
                    raise UploadError("signer_not_approved")
                source = session.scalar(select(AppArtifactSource).where(AppArtifactSource.artifact_id == artifact_id,
                    AppArtifactSource.storage_mode == "internal", AppArtifactSource.bucket == stored.bucket,
                    AppArtifactSource.object_key == stored.key, AppArtifactSource.object_version_id == stored.version_id,
                    AppArtifactSource.state == "verified"))
                if source is None:
                    revision = (session.scalar(select(func.max(AppArtifactSource.source_revision)).where(
                        AppArtifactSource.artifact_id == artifact_id)) or 0) + 1
                    session.add(AppArtifactSource(artifact_id=artifact_id, source_revision=revision,
                        storage_mode="internal", access_mode="presigned", bucket=stored.bucket, object_key=stored.key,
                        object_version_id=stored.version_id, object_etag=stored.etag, credential_config_ref="configured-minio",
                        allowed_hosts=list(self.store.allowed_hosts), state="verified", verified_sha256=digest,
                        verified_size_bytes=size, verified_at=now(), verification_evidence_ref=artifact.verification_evidence_ref,
                        availability_checked_at=now(), availability_state="available", created_by=actor))
                job.state, job.resolved_artifact_id, job.cleanup_pending = "succeeded", artifact_id, True
                job.error_code = None
                self.audit(session, job, "succeeded")
            self.cleanup(upload_id)
        except Exception as exc:
            code = exc.code if isinstance(exc, (UploadError, VerificationError, StorageError)) else "apk_upload_internal_error"
            retryable = isinstance(exc, StorageError) and code in ("apk_storage_unavailable", "apk_bucket_missing", "apk_bucket_versioning_required")
            clean = False
            with self.db.session() as session:
                job = session.scalar(select(AppUpload).where(AppUpload.upload_id == upload_id).with_for_update())
                if job.lease_token == token and job.state == "processing":
                    job.state = "retryable" if retryable else "failed"
                    job.error_code, job.cleanup_pending = code, not retryable
                    job.lease_until = now() + timedelta(seconds=30)
                    self.audit(session, job, "failed")
                    clean = not retryable
            if clean:
                self.cleanup(upload_id)
        return True

    @staticmethod
    def audit(session, job, result):
        session.add(AppAudit(actor_id=job.actor_id, action="apk_upload", resource_id=job.artifact_id,
            idempotency_key=str(uuid4()), request_sha256=job.request_sha256 or "0" * 64,
            reason=audit_text(job.reason or "APK upload interrupted"), result=result,
            details={"uploadId": job.upload_id, "errorCode": job.error_code, "sha256": job.sha256,
                "artifactIds": [job.resolved_artifact_id or job.artifact_id],
                "sourceBindings": ApkUploads.source_bindings(session, job)}))

    @staticmethod
    def source_bindings(session, job):
        return [dict(sourceId=s.source_id, sourceRevision=s.source_revision) for s in session.scalars(
            select(AppArtifactSource).where(AppArtifactSource.artifact_id == (job.resolved_artifact_id or job.artifact_id)))]

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try:
                    self.recover()
                    self.process_one()
                except Exception:
                    logging.getLogger(__name__).error("apk_worker_iteration_failed")
                self.stop_event.wait(2)
        self.thread = threading.Thread(target=loop, name="apk-upload-worker", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
