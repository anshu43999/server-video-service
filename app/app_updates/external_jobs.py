"""External registration shares the durable bounded queue, never MinIO bytes."""
from dataclasses import asdict
from datetime import timedelta
import hashlib
import json
import os
from uuid import uuid4

from sqlalchemy import func, or_, select, update

from .apk_verifier import Expectations, VerificationError
from .external_fetch import FetchError, hostname, validate_url
from .models import AppArtifact, AppArtifactSource, AppAudit, AppIdentity, AppUpload
from .uploads import ApkUploads, UploadError, now
from .verification_jobs import BuildCompatibility, VerificationJobs
from .security import audit_text


class ExternalJobs(ApkUploads):
    kind = "external"

    def __init__(self, database, verifier, fetcher, **kwargs):
        super().__init__(database, verifier, None, **kwargs)
        self.fetcher = fetcher

    @staticmethod
    def audit(session, job, result):
        session.add(AppAudit(actor_id=job.actor_id, action="external_apk", resource_id=job.artifact_id,
            idempotency_key=str(uuid4()), request_sha256=job.request_sha256,
            reason=audit_text(job.reason or "External APK recovery"), result=result,
            details={"jobId": job.upload_id, "errorCode": job.error_code, "sha256": job.sha256,
                "artifactIds": [job.resolved_artifact_id or job.artifact_id],
                "sourceBindings": ApkUploads.source_bindings(session, job)}))

    def register(self, actor, request, *, target_artifact_id=None):
        hosts = request.allowedDownloadHosts
        if len(set(hosts)) != len(hosts):
            raise UploadError("external_host_invalid", 422)
        try:
            for host in hosts:
                hostname(host)
            validate_url(request.downloadUrl, hosts)
        except FetchError as exc:
            raise UploadError(exc.code, 422) from None
        self.compatibility.validate()
        digest = hashlib.sha256(json.dumps([request.model_dump(), target_artifact_id, asdict(self.compatibility)],
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        identity = str(uuid4())
        with self.db.session() as session:
            app = session.scalar(select(AppIdentity).with_for_update())
            self.authorize(session, actor)
            if not app or not app.approved_signer_sha256:
                raise UploadError("signer_not_configured", 503)
            session.execute(update(AppIdentity).where(AppIdentity.package_name == app.package_name).values(
                version_high_water=AppIdentity.version_high_water))
            previous = session.scalar(select(AppUpload).where(AppUpload.actor_id == actor,
                AppUpload.idempotency_key == request.idempotencyKey))
            if previous:
                if previous.kind != self.kind or previous.request_sha256 != digest:
                    raise UploadError("idempotency_conflict")
                identity = previous.upload_id
            else:
                if target_artifact_id:
                    target = session.get(AppArtifact, target_artifact_id)
                    if not target or target.state != "verified" or target.sha256 != request.expectedArtifactSha256:
                        raise UploadError("artifact_not_verified")
                count = session.scalar(select(func.count()).select_from(AppUpload).where(or_(
                    AppUpload.state.in_(["receiving", "queued", "processing", "retryable"]), AppUpload.cleanup_pending.is_(True))))
                if count >= self.max_jobs:
                    raise UploadError("apk_upload_capacity", 429)
                artifact_id = str(uuid4())
                session.add(AppArtifact(artifact_id=artifact_id, package_name=app.package_name,
                    publisher_id=app.publisher_id, created_by=actor))
                session.flush()
                job = AppUpload(upload_id=identity, artifact_id=artifact_id, actor_id=actor,
                    kind=self.kind, external_url=request.downloadUrl, external_hosts=hosts,
                    target_artifact_id=target_artifact_id, compatibility=asdict(self.compatibility),
                    state="queued", reason=audit_text(request.reason), idempotency_key=request.idempotencyKey,
                    request_sha256=digest, lease_until=now())
                session.add(job)
                self.audit(session, job, "accepted")
        return self.status(identity)

    def process_one(self):
        token = str(uuid4())
        with self.db.session() as session:
            eligible = or_(AppUpload.state == "queued", (AppUpload.state == "retryable") & (AppUpload.lease_until <= now()))
            job = session.scalar(select(AppUpload).where(AppUpload.kind == self.kind, eligible).order_by(
                AppUpload.created_at).with_for_update(skip_locked=True))
            if not job:
                return False
            identity, actor, artifact_id = job.upload_id, job.actor_id, job.artifact_id
            if session.execute(update(AppUpload).where(AppUpload.upload_id == identity, eligible).values(
                state="processing", lease_token=token, lease_until=now() + timedelta(seconds=self.lease_seconds),
                attempts=AppUpload.attempts + 1).execution_options(synchronize_session=False)).rowcount != 1:
                return False
            url, hosts, target_id = job.external_url, list(job.external_hosts), job.target_artifact_id
            compatibility = BuildCompatibility(**job.compatibility)
        def guard(session):
            current = session.scalar(select(AppUpload).where(AppUpload.upload_id == identity).with_for_update())
            if current.state != "processing" or current.lease_token != token:
                raise UploadError("upload_lease_lost")
            self.authorize(session, actor)
            return current
        # Per-attempt file paths prevent an expired worker from deleting or
        # truncating the next worker's input during recovery.
        path = self.root / (identity + "-" + token + ".apk")
        try:
            with self.db.session() as session:
                guard(session)
            self.root.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                fetched = self.fetcher.fetch(url, hosts, output)
                output.flush()
                os.fsync(output.fileno())
            with self.db.session() as session:
                job = guard(session)
                job.fetch_evidence = fetched.evidence
                if job.sha256 and (job.sha256 != fetched.sha256 or job.size_bytes != fetched.size):
                    raise UploadError("external_file_changed")
                job.sha256, job.size_bytes = fetched.sha256, fetched.size
                original = session.get(AppArtifact, artifact_id)
                if original.state == "verifying":
                    original.state, original.error_code = "failed", "verification_interrupted"
                # Check a known target BEFORE touching its global version slot.
                if target_id:
                    target = session.get(AppArtifact, target_id)
                    if not target or target.sha256 != fetched.sha256 or target.size_bytes != fetched.size:
                        raise UploadError("external_file_changed")
                resolved = job.resolved_artifact_id or (artifact_id if original.state == "verified" else None)
            if not resolved:
                resolved = VerificationJobs(self.db, self.verifier).verify_file(artifact_id, path,
                    actor_id=actor, compatibility=compatibility,
                    expected=Expectations(size_bytes=fetched.size, sha256=fetched.sha256), guard=guard)
            with self.db.session() as session:
                app = session.scalar(select(AppIdentity).with_for_update())
                job = guard(session)
                artifact = session.get(AppArtifact, resolved)
                if (artifact.state != "verified" or artifact.signer_sha256 != app.approved_signer_sha256
                        or artifact.sha256 != fetched.sha256 or artifact.size_bytes != fetched.size
                        or (target_id and target_id != resolved)):
                    raise UploadError("external_file_changed")
                sources = session.scalars(select(AppArtifactSource).where(AppArtifactSource.artifact_id == resolved,
                    AppArtifactSource.public_url == url, AppArtifactSource.state == "verified")).all()
                source = next((value for value in sources if value.allowed_hosts == hosts), None)
                if source is None:
                    revision = (session.scalar(select(func.max(AppArtifactSource.source_revision)).where(
                        AppArtifactSource.artifact_id == resolved)) or 0) + 1
                    session.add(AppArtifactSource(artifact_id=resolved, source_revision=revision,
                        storage_mode="external", access_mode="public", public_url=url, allowed_hosts=hosts,
                        state="verified", verified_sha256=fetched.sha256, verified_size_bytes=fetched.size,
                        verified_at=now(), verification_evidence_ref=artifact.verification_evidence_ref,
                        availability_checked_at=now(), availability_state="available", created_by=actor))
                job.resolved_artifact_id, job.state = resolved, "succeeded"
                job.error_code, job.cleanup_pending = None, True
                self.audit(session, job, "succeeded")
        except Exception as exc:
            code = exc.code if isinstance(exc, (UploadError, VerificationError, FetchError)) else "external_internal_error"
            with self.db.session() as session:
                job = session.scalar(select(AppUpload).where(AppUpload.upload_id == identity).with_for_update())
                if job.state == "processing" and job.lease_token == token:
                    job.state, job.error_code, job.cleanup_pending = "failed", code, True
                    original = session.get(AppArtifact, artifact_id)
                    if original.state in ("pending", "verifying"):
                        original.state, original.error_code = "failed", code
                    self.audit(session, job, "failed")
        finally:
            # Only unlink this attempt. Queue cleanup also retries all attempts
            # after success/failure; never keep a hosted replica of the APK.
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            self.cleanup(identity)
        return True

    def cleanup(self, upload_id):
        # Lock the job while enumerating paths. Processing attempts retain their
        # own file; only terminal jobs may have all attempt files removed.
        with self.db.session() as session:
            job = session.scalar(select(AppUpload).where(AppUpload.upload_id == upload_id).with_for_update())
            if not job or job.state not in ("failed", "succeeded"):
                return False
            try:
                for path in self.root.glob(upload_id + "-*.apk"):
                    path.unlink(missing_ok=True)
            except OSError:
                job.cleanup_pending = True
                return False
            job.cleanup_pending = False
        return True

    def recover(self):
        super().recover()
        # A killed process may have left a per-attempt file while the job is
        # queued for retry. Remove every file except an active attempt token.
        with self.db.session() as session:
            jobs = session.scalars(select(AppUpload).where(AppUpload.kind == self.kind).with_for_update(skip_locked=True)).all()
            for job in jobs:
                active = job.upload_id + "-" + str(job.lease_token) + ".apk" if job.state == "processing" else None
                for path in self.root.glob(job.upload_id + "-*.apk"):
                    if path.name == active:
                        continue
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        job.cleanup_pending = True
