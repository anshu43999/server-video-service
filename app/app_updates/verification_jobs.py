"""Internal worker transition, used by future MinIO/external registration APIs.

Caller authorizes the platform admin and gives an immutable staged file. The
worker never accepts a URL. Long-running parsing runs outside the DB transaction;
identity/high-water/state are rechecked under CAS before committing verification.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .apk_verifier import ApkVerifier, Expectations, VerificationError
from .models import AppArtifact, AppAudit, AppIdentity


@dataclass(frozen=True)
class BuildCompatibility:
    # These are trusted build/CI assertions, NOT facts extracted from the APK.
    # Promotion APIs must authorize their provenance separately.
    server_contract_min: int
    server_contract_max: int
    data_schema_version: int
    readable_schema_min: int
    readable_schema_max: int
    evidence_ref: str

    def validate(self):
        values = (self.server_contract_min, self.server_contract_max, self.data_schema_version,
                  self.readable_schema_min, self.readable_schema_max)
        if (any(type(v) is not int or not 1 <= v <= 2147483647 for v in values)
                or self.server_contract_min > self.server_contract_max
                or not self.readable_schema_min <= self.data_schema_version <= self.readable_schema_max
                or not self.evidence_ref or len(self.evidence_ref) > 512):
            raise VerificationError("build_compatibility_missing")


class VerificationJobs:
    def __init__(self, database, verifier: ApkVerifier):
        self.database, self.verifier = database, verifier

    def verify_file(self, artifact_id: str, staged_file: Path, *, actor_id: str,
                    compatibility: BuildCompatibility, expected: Expectations | None = None, guard=None):
        operation = str(uuid4())
        with self.database.session() as session:
            if guard:
                guard(session)
            artifact = session.get(AppArtifact, artifact_id)
            if artifact is None:
                raise VerificationError("artifact_not_found")
            identity = session.get(AppIdentity, artifact.package_name)
            if identity is None or identity.publisher_id != artifact.publisher_id:
                raise VerificationError("identity_not_configured")
            if artifact.state not in ("pending", "failed"):
                raise VerificationError("artifact_verification_conflict")
            claimed = session.execute(update(AppArtifact).where(AppArtifact.artifact_id == artifact_id,
                AppArtifact.state == artifact.state).values(state="verifying", error_code=None)).rowcount
            if claimed != 1:
                raise VerificationError("artifact_verification_conflict")
            package, publisher = artifact.package_name, artifact.publisher_id
            signer = identity.approved_signer_sha256
        evidence = None
        try:
            compatibility.validate()
            # Same previously verified bytes are idempotently reusable even
            # after the high-water advanced; final transaction revalidates it.
            with staged_file.open("rb") as stream:
                result = self.verifier.verify(stream, approved_signer_sha256=signer,
                    high_water=0, expected=expected, enforce_first_version=False)
            evidence = result.evidence_ref
            with self.database.session() as session:
                identity = session.execute(select(AppIdentity).where(AppIdentity.package_name == package).with_for_update()).scalar_one()
                if guard:
                    guard(session)
                artifact = session.get(AppArtifact, artifact_id)
                if artifact.state != "verifying" or artifact.package_name != package or artifact.publisher_id != publisher:
                    raise VerificationError("artifact_verification_conflict", evidence)
                if identity.publisher_id != publisher or identity.approved_signer_sha256 != result.signer_sha256:
                    raise VerificationError("signer_not_approved", evidence)
                existing = session.scalar(select(AppArtifact).where(AppArtifact.package_name == package,
                    AppArtifact.version_code == result.version_code, AppArtifact.state == "verified"))
                if existing and existing.sha256 == result.sha256 and existing.signer_sha256 == result.signer_sha256:
                    artifact.state, artifact.error_code = "failed", "duplicate_existing_artifact"
                    artifact.verification_evidence_ref = evidence
                    self._audit(session, artifact_id, actor_id, operation, "succeeded", "duplicate_existing_artifact", evidence,
                                result.sha256, existing.artifact_id)
                    return existing.artifact_id
                previous = identity.version_high_water
                if (previous == 0 and result.version_code != 1) or result.version_code <= previous:
                    raise VerificationError("version_not_increasing", evidence)
                changed = session.execute(update(AppIdentity).where(AppIdentity.package_name == package,
                    AppIdentity.version_high_water == previous,
                    AppIdentity.approved_signer_sha256 == result.signer_sha256).values(version_high_water=result.version_code)).rowcount
                if changed != 1:
                    raise VerificationError("version_allocation_conflict", evidence)
                artifact.state = "verified"
                artifact.version_code, artifact.version_name = result.version_code, result.version_name
                artifact.size_bytes, artifact.sha256 = result.size_bytes, result.sha256
                artifact.signer_sha256, artifact.min_sdk, artifact.abis = result.signer_sha256, result.min_sdk, list(result.abis)
                artifact.server_contract_min, artifact.server_contract_max = compatibility.server_contract_min, compatibility.server_contract_max
                artifact.data_schema_version = compatibility.data_schema_version
                artifact.readable_schema_min, artifact.readable_schema_max = compatibility.readable_schema_min, compatibility.readable_schema_max
                artifact.verification_evidence_ref, artifact.verified_at = evidence, datetime.now(timezone.utc)
                artifact.build_provenance = {**artifact.build_provenance, "compatibilityEvidenceRef": compatibility.evidence_ref}
                artifact.error_code = None
                self._audit(session, artifact_id, actor_id, operation, "succeeded", None, evidence, result.sha256)
            return artifact_id
        except (VerificationError, OSError, IntegrityError) as exc:
            code = (exc.code if isinstance(exc, VerificationError) else
                    "version_allocation_conflict" if isinstance(exc, IntegrityError) else "verification_io_error")
            evidence = getattr(exc, "evidence_ref", None) or evidence
            with self.database.session() as session:
                if guard:
                    guard(session)
                session.execute(update(AppArtifact).where(AppArtifact.artifact_id == artifact_id,
                    AppArtifact.state == "verifying").values(state="failed", error_code=code, verification_evidence_ref=evidence))
                self._audit(session, artifact_id, actor_id, operation, "failed", code, evidence)
            raise VerificationError(code, evidence) from exc
        except Exception as exc:
            # Unexpected parser/worker failures must not leave a publishable
            # result or a silent forever-verifying record. No raw error text
            # (possibly containing a source path) goes into audit/API fields.
            with self.database.session() as session:
                if guard:
                    guard(session)
                session.execute(update(AppArtifact).where(AppArtifact.artifact_id == artifact_id,
                    AppArtifact.state == "verifying").values(state="failed", error_code="verification_internal_error"))
                self._audit(session, artifact_id, actor_id, operation, "failed", "verification_internal_error", evidence)
            raise VerificationError("verification_internal_error", evidence) from exc

    @staticmethod
    def _audit(session, artifact_id, actor, operation, result, code, evidence, sha256=None, existing_id=None):
        details = {"errorCode": code, "evidenceRefSha256": hashlib.sha256(evidence.encode()).hexdigest() if evidence else None,
                   "sha256": sha256, "existingArtifactId": existing_id, "artifactIds": [existing_id or artifact_id]}
        digest = hashlib.sha256(json.dumps([artifact_id, operation], separators=(",", ":")).encode()).hexdigest()
        session.add(AppAudit(actor_id=actor, action="verify_apk", resource_id=artifact_id,
            idempotency_key=operation, request_sha256=digest, reason="APK verification worker",
            result=result, details=details))
