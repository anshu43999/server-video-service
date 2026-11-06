"""Transactional App releases and device reports, separate from model updates."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update

from ..database import AccountRecord
from . import contract as c
from .external_fetch import FetchError, validate_url
from .models import (AppIdentity, AppArtifact, AppArtifactSource, AppPolicy, AppRelease,
                     AppPolicyRevision, AppDeviceState, AppReceipt, AppAudit, AppUpload, AppRollback)
from .publisher import json_bytes
from .security import audit_text, session_valid


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(timezone.utc)


def digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


class UpdateError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# Local/offline work, diagnostics, account exit and update access cannot be
# disabled by an App compatibility gate. Operators declare online capabilities.
PROTECTED = {"app.update", "updates", "diagnostics", "account.logout", "logout", "local.data", "recovery"}


class AppUpdates:
    def __init__(self, database, publisher, *, scopes, server_contract_version=1,
                 gate_capabilities=(), tickets=None, max_devices=100000, max_receipts_per_device=10000,
                 recovery_evidence=()):
        self.db, self.publisher, self.tickets = database, publisher, tickets
        self.scope_values = [c.Scope.model_validate(v).model_dump() for v in scopes]
        self.scopes = {tuple(v.values()) for v in self.scope_values}
        if not self.scopes or server_contract_version < 1:
            raise ValueError("explicit App deployment scopes required")
        self.server_contract = server_contract_version
        if max_devices < 1 or max_receipts_per_device < 1:
            raise ValueError("invalid device report limits")
        self.max_devices, self.max_receipts = max_devices, max_receipts_per_device
        self.recovery_evidence = list(recovery_evidence)
        self.gate_capabilities = set(gate_capabilities)
        if self.gate_capabilities & PROTECTED:
            raise ValueError("protected capability cannot be restricted")

    def configuration(self, actor):
        with self.db.session() as session:
            self.authorize(session, actor)
            return dict(scopes=self.scope_values, gateCapabilities=sorted(self.gate_capabilities),
                maxApkBytes=getattr(self, "max_apk_bytes", 8 * 1024**3),
                uploadEnabled=getattr(self, "upload_enabled", False),
                externalEnabled=getattr(self, "external_enabled", False))

    def scope(self, body):
        values = body.model_dump(include=set(c.Scope.model_fields))
        if tuple(values.values()) not in self.scopes:
            raise UpdateError("deployment_not_allowed")
        return values

    def identity(self, session, body, *, readonly=False):
        self.scope(body)
        identity = session.scalar(select(AppIdentity).where(AppIdentity.package_name == body.packageName).with_for_update())
        if not identity or identity.publisher_id != body.publisherId:
            raise UpdateError("deployment_not_allowed")
        # SQLite also needs a write lock before any dependent reads. PostgreSQL
        # takes a row lock above. All publish/stop/check/permission/report paths
        # use this order, including policy creation and receipt deduplication.
        if not readonly:
            session.execute(update(AppIdentity).where(AppIdentity.package_name == identity.package_name).values(
                version_high_water=AppIdentity.version_high_water))
        if (not identity.approved_signer_sha256
                or identity.metadata_key_config_ref != self.publisher.key_id):
            raise UpdateError("service_unavailable")
        return identity

    def authorize(self, session, actor):
        if not session_valid(session, actor):
            raise UpdateError("authentication_required")
        account = session.scalar(select(AccountRecord).where(AccountRecord.account_id == actor).with_for_update())
        if not account or not account.enabled or account.platform_role != "PLATFORM_ADMIN":
            raise UpdateError("platform_admin_required")

    def policy(self, session, body, *, create=False, actor=None):
        policy = session.scalar(select(AppPolicy).where(AppPolicy.publisher_id == body.publisherId,
            AppPolicy.package_name == body.packageName, AppPolicy.channel == body.channel,
            AppPolicy.deployment_id == body.deploymentId))
        if policy is None and create:
            policy = AppPolicy(package_name=body.packageName, publisher_id=body.publisherId,
                channel=body.channel, deployment_id=body.deploymentId, updated_by=actor,
                revision=1, min_supported_version_code=1, selection={}, restricted_capabilities=[])
            session.add(policy)
            session.flush()
        if policy is None:
            raise UpdateError("service_unavailable")
        return policy

    def duplicate(self, session, actor, action, body):
        previous = session.scalar(select(AppAudit).where(AppAudit.actor_id == actor, AppAudit.action == action,
            AppAudit.idempotency_key == body.idempotencyKey))
        if previous:
            if previous.request_sha256 != digest(body.model_dump(mode="json")):
                raise UpdateError("idempotency_conflict")
            return previous.details["response"]

    def audit(self, session, actor, action, body, policy, result, before):
        release_ids = list(getattr(body, "affectedReleaseIds", []))
        for field in ("releaseId", "stableReleaseId", "recoveryReleaseId"):
            value = getattr(body, field, None)
            if value:
                release_ids.append(value)
        artifacts = set()
        if getattr(body, "artifactId", None):
            artifacts.add(body.artifactId)
        for release_id in release_ids:
            release = session.get(AppRelease, release_id)
            if release:
                artifacts.add(release.artifact_id)
        bindings = [b for b in policy.selection.get("releases", []) if b["artifactId"] in artifacts]
        prior = session.scalar(select(AppPolicyRevision).where(AppPolicyRevision.policy_id == policy.policy_id,
            AppPolicyRevision.revision == before))
        if prior:
            bindings.extend(b for b in prior.snapshot.get("selection", {}).get("releases", [])
                            if b["artifactId"] in artifacts and b not in bindings)
        if getattr(body, "sourceId", None):
            bindings = [*bindings, dict(sourceId=body.sourceId, sourceRevision=body.sourceRevision)]
        session.add(AppAudit(policy_id=policy.policy_id, actor_id=actor, action=action,
            resource_id=result["resourceId"], idempotency_key=body.idempotencyKey,
            request_sha256=digest(body.model_dump(mode="json")), before_revision=before,
            after_revision=policy.revision, reason=audit_text(body.reason), result="succeeded",
            details={"response": result, "artifactIds": sorted(artifacts), "sourceBindings": bindings}))

    def artifact(self, session, identity, artifact_id):
        artifact = session.get(AppArtifact, artifact_id)
        if (not artifact or artifact.state != "verified" or artifact.package_name != identity.package_name
                or artifact.publisher_id != identity.publisher_id or not artifact.verification_evidence_ref):
            raise UpdateError("artifact_not_verified")
        if artifact.signer_sha256 != identity.approved_signer_sha256:
            raise UpdateError("signer_not_approved")
        return artifact

    def rejected(self, actor, body, action, code):
        """Separate audit transaction after a failed mutation has rolled back."""
        if actor is None or body is None:
            return
        with self.db.session() as session:
            policy = session.scalar(select(AppPolicy).where(AppPolicy.package_name == body.packageName,
                AppPolicy.publisher_id == body.publisherId, AppPolicy.channel == body.channel,
                AppPolicy.deployment_id == body.deploymentId))
            revision = policy.revision if policy else None
            session.add(AppAudit(policy_id=policy.policy_id if policy else None, actor_id=actor,
                action="app_" + action + "_rejected", resource_id=getattr(body, "releaseId", "request"),
                idempotency_key=str(uuid4()), request_sha256=digest(body.model_dump(mode="json")),
                before_revision=revision, after_revision=revision, reason=audit_text(body.reason),
                result="rejected", details={"errorCode": code,
                    "expectedPolicyRevision": getattr(body, "expectedPolicyRevision", None),
                    "artifactIds": [body.artifactId] if getattr(body, "artifactId", None) else [],
                    "sourceBindings": [dict(sourceId=body.sourceId, sourceRevision=body.sourceRevision)]
                        if getattr(body, "sourceId", None) else []}))

    def source(self, session, artifact, source_id, revision):
        source = session.get(AppArtifactSource, source_id)
        if not source or source.artifact_id != artifact.artifact_id or source.state != "verified":
            raise UpdateError("source_not_verified")
        if source.source_revision != revision:
            raise UpdateError("source_revision_conflict")
        if (source.verified_sha256 != artifact.sha256 or source.verified_size_bytes != artifact.size_bytes
                or not source.verification_evidence_ref):
            raise UpdateError("source_not_verified")
        if source.availability_state != "available" or not source.allowed_hosts:
            raise UpdateError("source_unavailable")
        if source.storage_mode == "external":
            try:
                validate_url(source.public_url, source.allowed_hosts)
            except (ValueError, FetchError):
                raise UpdateError("source_not_verified") from None
        elif source.access_mode != "presigned" or not source.object_version_id or not source.object_etag:
            raise UpdateError("source_not_verified")
        return source

    def draft(self, actor, body):
        with self.db.session() as session:
            identity = self.identity(session, body)
            self.authorize(session, actor)
            previous = self.duplicate(session, actor, "app_release_draft", body)
            if previous:
                return previous
            policy = self.policy(session, body, create=True, actor=actor)
            artifact = self.artifact(session, identity, body.artifactId)
            if session.scalar(select(AppRelease).where(AppRelease.policy_id == policy.policy_id,
                    AppRelease.artifact_id == artifact.artifact_id)):
                raise UpdateError("idempotency_conflict")
            release = AppRelease(artifact_id=artifact.artifact_id, policy_id=policy.policy_id,
                package_name=identity.package_name, publisher_id=identity.publisher_id,
                importance=body.importance, notes=body.notes, created_by=actor)
            session.add(release)
            session.flush()
            result = dict(resourceId=release.release_id, state="draft", revision=policy.revision)
            self.audit(session, actor, "app_release_draft", body, policy, result, policy.revision)
            return result

    def release(self, session, policy, release_id):
        release = session.get(AppRelease, release_id)
        if not release or release.policy_id != policy.policy_id:
            raise UpdateError("release_not_found")
        return release

    def compatible(self, artifact, context):
        return (artifact.min_sdk <= context["sdkInt"] and bool(set(artifact.abis) & set(context["supportedAbis"]))
                and artifact.server_contract_min <= self.server_contract <= artifact.server_contract_max
                and context["serverContractVersion"] == self.server_contract)

    def snapshot(self, session, actor, policy, body, before, selection):
        changed = session.execute(update(AppPolicy).where(AppPolicy.policy_id == policy.policy_id,
            AppPolicy.revision == before).values(revision=before + 1, selection=selection,
                min_supported_version_code=policy.min_supported_version_code,
                restricted_capabilities=policy.restricted_capabilities, updated_by=actor,
                updated_at=now()), execution_options={"synchronize_session": False}).rowcount
        if changed != 1:
            raise UpdateError("policy_revision_conflict")
        session.refresh(policy)
        value = self.scope(body) | dict(messageType="policy_snapshot", policyId=policy.policy_id,
            policyRevision=policy.revision, minSupportedVersionCode=policy.min_supported_version_code,
            restrictedCapabilities=policy.restricted_capabilities, selection=selection)
        signed = self.publisher.sign(value)
        session.add(AppPolicyRevision(policy_id=policy.policy_id, revision=policy.revision, snapshot=value,
            snapshot_sha256=digest(value), key_id=signed["keyId"], payload_base64url=signed["payloadBase64Url"],
            signature_base64url=signed["signatureBase64Url"], created_by=actor))

    def publish(self, actor, body):
        with self.db.session() as session:
            identity = self.identity(session, body)
            self.authorize(session, actor)
            previous = self.duplicate(session, actor, "app_release_publish", body)
            if previous:
                return previous
            policy = self.policy(session, body)
            if policy.revision != body.expectedPolicyRevision:
                raise UpdateError("policy_revision_conflict")
            release = self.release(session, policy, body.releaseId)
            if release.state == "stopped":
                raise UpdateError("release_stopped")
            if release.state != "draft" or release.purpose != "normal":
                raise UpdateError("invalid_request")
            artifact = self.artifact(session, identity, release.artifact_id)
            source = self.source(session, artifact, body.sourceId, body.sourceRevision)
            if not artifact.server_contract_min <= self.server_contract <= artifact.server_contract_max:
                raise UpdateError("compatibility_gate_unreachable")
            floor = body.minSupportedVersionCode
            if (floor > artifact.version_code or (floor > 1) != bool(body.restrictedCapabilities)
                    or not set(body.restrictedCapabilities) <= self.gate_capabilities):
                raise UpdateError("compatibility_gate_unreachable")
            # Publish order cannot silently replace a newer active target with
            # older behavior. Recovery operations are a separate T07 workflow.
            for binding in policy.selection.get("releases", []):
                other = session.get(AppArtifact, binding["artifactId"])
                if other and other.version_code >= artifact.version_code:
                    raise UpdateError("version_not_increasing")
            devices = session.scalars(select(AppDeviceState).where(AppDeviceState.policy_id == policy.policy_id,
                AppDeviceState.current_version_code < floor)).all()
            if any(not device.observed.get("context") or not self.compatible(artifact, device.observed["context"])
                   for device in devices):
                raise UpdateError("compatibility_gate_unreachable")
            if source.storage_mode == "internal":
                self.address(source, artifact, now(), now() + timedelta(seconds=900))
            binding = dict(releaseId=release.release_id, artifactId=artifact.artifact_id,
                sourceId=source.source_id, sourceRevision=source.source_revision)
            selection = dict(policy.selection)
            if len(selection.get("releases", [])) >= 100:
                raise UpdateError("service_unavailable")
            selection["releases"] = [*selection.get("releases", []), binding]
            release.state, release.published_at = "published", now()
            before = policy.revision
            policy.min_supported_version_code, policy.restricted_capabilities = floor, body.restrictedCapabilities
            # Explicit flush before CAS keeps ORM autoflush from replaying an
            # old revision over the compare-and-swap update.
            session.flush()
            self.snapshot(session, actor, policy, body, before, selection)
            result = dict(resourceId=release.release_id, state="published", revision=policy.revision)
            self.audit(session, actor, "app_release_publish", body, policy, result, before)
            return result

    def stop(self, actor, body):
        with self.db.session() as session:
            self.identity(session, body)
            self.authorize(session, actor)
            previous = self.duplicate(session, actor, "app_release_stop", body)
            if previous:
                return previous
            policy = self.policy(session, body)
            if policy.revision != body.expectedPolicyRevision:
                raise UpdateError("policy_revision_conflict")
            release = self.release(session, policy, body.releaseId)
            if release.state == "stopped":
                raise UpdateError("release_stopped")
            before = policy.revision
            release.state, release.stopped_at = "stopped", now()
            selection = dict(policy.selection)
            selection["releases"] = [b for b in selection.get("releases", []) if b["releaseId"] != release.release_id]
            selection["stoppedReleaseIds"] = list(dict.fromkeys([*selection.get("stoppedReleaseIds", []), release.release_id]))
            if release.purpose == "recovery":
                selection["recoveryPendingVersionCodes"] = sorted(set(selection.get("recoveryPendingVersionCodes", []))
                    | set(selection.get("recoveryVersionCodes", {}).get(release.release_id, [])))
            # Stopping must remain possible even when the last reachable target
            # disappears; clear the gate instead of trapping old clients.
            policy.min_supported_version_code, policy.restricted_capabilities = 1, []
            session.flush()
            self.snapshot(session, actor, policy, body, before, selection)
            result = dict(resourceId=release.release_id, state="stopped", revision=policy.revision)
            self.audit(session, actor, "app_release_stop", body, policy, result, before)
            return result

    def rollback_preview(self, actor, body):
        from .rollback import preview
        return preview(self, actor, body)

    def rollback_apply(self, actor, body):
        from .rollback import apply
        return apply(self, actor, body)

    def rollback_read(self, actor, operation_id):
        from .rollback import read
        return read(self, actor, operation_id)

    def base(self, body, policy, seconds):
        issued = now()
        return body.model_dump(include=set(c.ClientContext.model_fields)) | dict(policyRevision=policy.revision,
            issuedAt=issued, authorizationExpiresAt=issued + timedelta(seconds=seconds))

    def signed(self, model, values):
        payload = model.model_validate(values)
        return self.publisher.sign(payload.model_dump(mode="json"))

    def contact(self, session, policy, body):
        device = session.get(AppDeviceState, (policy.policy_id, body.installationId))
        if device is None:
            if session.scalar(select(func.count()).select_from(AppDeviceState).where(
                    AppDeviceState.policy_id == policy.policy_id)) >= self.max_devices:
                raise UpdateError("rate_limited")
            device = AppDeviceState(policy_id=policy.policy_id, installation_id=body.installationId,
                current_version_code=body.currentVersionCode, last_policy_revision=0,
                last_sequence=0, stage="not_discovered", observed={})
            session.add(device)
            session.flush()
        device.last_contact_at = now()
        device.current_version_code = max(device.current_version_code, body.currentVersionCode)
        return device

    def target(self, release, artifact, source, selection):
        recovery = selection.get("recoveryBindings", {}).get(release.release_id, {}) if release.purpose == "recovery" else {}
        return dict(releaseId=release.release_id, artifactId=artifact.artifact_id, sourceId=source.source_id,
            sourceRevision=source.source_revision, versionCode=artifact.version_code, versionName=artifact.version_name,
            sizeBytes=artifact.size_bytes, sha256=artifact.sha256, signerSha256=artifact.signer_sha256,
            minSdk=artifact.min_sdk, abis=artifact.abis,
            serverContractRange=dict(min=artifact.server_contract_min, max=artifact.server_contract_max),
            dataSchemaVersion=artifact.data_schema_version,
            readableDataSchemaRange=dict(min=artifact.readable_schema_min, max=artifact.readable_schema_max),
            publishedAt=aware(release.published_at), notes=release.notes, importance=release.importance,
            releasePurpose=release.purpose, rollbackOperationId=recovery.get("rollbackOperationId"),
            restoresBehaviorFromReleaseId=recovery.get("restoresBehaviorFromReleaseId"),
            affectedReleaseIds=recovery.get("affectedReleaseIds", []))

    def check(self, body):
        with self.db.session() as session:
            identity = self.identity(session, body)
            policy = self.policy(session, body)
            if body.lastPolicyRevision > policy.revision:
                raise UpdateError("policy_revision_conflict")
            device = self.contact(session, policy, body)
            context = body.model_dump(include={"sdkInt", "supportedAbis", "signerSha256", "serverContractVersion"})
            device.observed = dict(device.observed) | {"context": context, "contextVersionCode": body.currentVersionCode}
            device.last_policy_revision = max(device.last_policy_revision, policy.revision)
            target, candidates, compatible = None, [], []
            supported = body.signerSha256 == identity.approved_signer_sha256 and body.serverContractVersion == self.server_contract
            if supported:
                for binding in policy.selection.get("releases", []):
                    release = self.release(session, policy, binding["releaseId"])
                    if release.state != "published":
                        continue
                    if release.purpose == "recovery" and body.currentVersionCode not in policy.selection.get("recoveryVersionCodes", {}).get(release.release_id, []):
                        continue
                    artifact = self.artifact(session, identity, binding["artifactId"])
                    if artifact.version_code <= body.currentVersionCode:
                        continue
                    candidates.append(artifact)
                    try:
                        source = self.source(session, artifact, binding["sourceId"], binding["sourceRevision"])
                    except UpdateError:
                        continue
                    if self.compatible(artifact, context):
                        compatible.append((release, artifact, source))
                if compatible:
                    release, artifact, source = max(compatible, key=lambda entry: entry[1].version_code)
                    target = self.target(release, artifact, source, policy.selection)
            pending = policy.selection.get("recoveryPendingVersionCodes", [])
            result = ("client_unsupported" if not supported else "update_available" if target else
                      "recovery_pending" if body.currentVersionCode in pending else
                      "no_compatible_release" if candidates else "up_to_date")
            gate = bool(target and body.currentVersionCode < policy.min_supported_version_code
                        and policy.min_supported_version_code <= target["versionCode"])
            compatibility = dict(minSupportedVersionCode=policy.min_supported_version_code if gate else 1,
                onlineAction="restrict_declared_capabilities" if gate else "allow",
                restrictedCapabilities=policy.restricted_capabilities if gate else [],
                reasonCode="minimum_supported_version" if gate else None)
            return self.signed(c.CheckPayload, self.base(body, policy, 900) | dict(messageType="check",
                result=result, release=target, compatibility=compatibility))

    def binding(self, session, identity, policy, body):
        release = self.release(session, policy, body.releaseId)
        if release.state == "stopped":
            raise UpdateError("release_stopped")
        if policy.revision != body.expectedPolicyRevision:
            raise UpdateError("policy_revision_conflict")
        if release.state != "published":
            raise UpdateError("release_not_found")
        if release.purpose == "recovery" and body.currentVersionCode not in policy.selection.get("recoveryVersionCodes", {}).get(release.release_id, []):
            raise UpdateError("recovery_incompatible")
        expected = dict(releaseId=body.releaseId, artifactId=body.artifactId,
            sourceId=body.sourceId, sourceRevision=body.sourceRevision)
        if expected not in policy.selection.get("releases", []):
            raise UpdateError("source_revision_conflict")
        artifact = self.artifact(session, identity, body.artifactId)
        source = self.source(session, artifact, body.sourceId, body.sourceRevision)
        if artifact.version_code <= body.currentVersionCode:
            raise UpdateError("version_not_increasing")
        if artifact.sha256 != body.sha256 or artifact.size_bytes != body.sizeBytes:
            raise UpdateError("artifact_not_verified")
        device = session.get(AppDeviceState, (policy.policy_id, body.installationId))
        context = device.observed.get("context", {}) if device else {}
        if (not context or device.observed.get("contextVersionCode") != body.currentVersionCode
                or device.current_version_code != body.currentVersionCode
                or context.get("signerSha256") != identity.approved_signer_sha256
                or not self.compatible(artifact, context)):
            raise UpdateError("compatibility_gate_unreachable")
        return artifact, source

    def address(self, source, artifact, issued, expires):
        if source.storage_mode == "external":
            return source.public_url, None
        try:
            if self.tickets is None:
                raise ValueError("MinIO not configured")
            return self.tickets(source, artifact, issued, expires)
        except Exception:
            raise UpdateError("source_unavailable") from None

    def permission(self, body, *, install=False):
        with self.db.session() as session:
            identity = self.identity(session, body)
            policy = self.policy(session, body)
            artifact, source = self.binding(session, identity, policy, body)
            values = self.base(body, policy, 120 if install else 900) | dict(releaseId=body.releaseId,
                artifactId=body.artifactId, sourceId=source.source_id, sourceRevision=source.source_revision,
                versionCode=artifact.version_code, sha256=artifact.sha256, sizeBytes=artifact.size_bytes,
                signerSha256=artifact.signer_sha256)
            if install:
                if body.verifiedVersionCode != artifact.version_code:
                    raise UpdateError("artifact_not_verified")
                if body.verifiedSignerSha256 != identity.approved_signer_sha256:
                    raise UpdateError("signer_not_approved")
                values.update(messageType="install_permission", permissionId=str(uuid4()),
                    userActionRequired=True, offlineInstallAllowed=False)
                model = c.InstallPermissionPayload
            else:
                url, expiry = self.address(source, artifact, values["issuedAt"], values["authorizationExpiresAt"])
                values.update(messageType="download", storageMode=source.storage_mode, accessMode=source.access_mode,
                    downloadUrl=url, downloadUrlExpiresAt=expiry, allowedDownloadHosts=source.allowed_hosts)
                model = c.DownloadPayload
            self.contact(session, policy, body)
            return self.signed(model, values)

    def download(self, body):
        return self.permission(body)

    def install(self, body):
        return self.permission(body, install=True)

    def receipt(self, body):
        with self.db.session() as session:
            self.identity(session, body)
            policy = self.policy(session, body)
            sha = digest(body.model_dump(mode="json"))
            existing = session.get(AppReceipt, (policy.policy_id, body.installationId, body.eventId))
            if existing:
                if existing.request_sha256 != sha:
                    raise UpdateError("idempotency_conflict")
                self.contact(session, policy, body)
                return c.ReceiptResult(eventId=body.eventId, accepted=True, duplicate=True,
                    receivedAt=aware(existing.created_at)).model_dump(mode="json")
            if body.policyRevision > policy.revision:
                raise UpdateError("policy_revision_conflict")
            if session.scalar(select(func.count()).select_from(AppReceipt).where(AppReceipt.policy_id == policy.policy_id,
                    AppReceipt.installation_id == body.installationId)) >= self.max_receipts:
                raise UpdateError("rate_limited")
            release = self.release(session, policy, body.releaseId)
            artifact = session.get(AppArtifact, release.artifact_id)
            history = session.get(AppPolicyRevision, (policy.policy_id, body.policyRevision))
            entries = history.snapshot.get("selection", {}).get("releases", []) if history else []
            bindings = [b for b in entries if b["releaseId"] == release.release_id and b["artifactId"] == body.artifactId]
            if (not bindings or body.artifactId != artifact.artifact_id or body.targetVersionCode != artifact.version_code
                    or (body.sourceId is not None and not any(b["sourceId"] == body.sourceId
                        and b["sourceRevision"] == body.sourceRevision for b in bindings))):
                raise UpdateError("invalid_request")
            if session.scalar(select(AppReceipt).where(AppReceipt.policy_id == policy.policy_id,
                    AppReceipt.installation_id == body.installationId, AppReceipt.attempt_id == body.attemptId,
                    AppReceipt.sequence == body.sequence)):
                raise UpdateError("idempotency_conflict")
            previous_attempt = session.scalar(select(AppReceipt).where(AppReceipt.policy_id == policy.policy_id,
                AppReceipt.installation_id == body.installationId, AppReceipt.attempt_id == body.attemptId).limit(1))
            if previous_attempt and (previous_attempt.release_id != body.releaseId
                    or previous_attempt.artifact_id != body.artifactId
                    or previous_attempt.from_version_code != body.fromVersionCode
                    or previous_attempt.target_version_code != body.targetVersionCode):
                raise UpdateError("idempotency_conflict")
            device = self.contact(session, policy, body)
            received = now()
            session.add(AppReceipt(policy_id=policy.policy_id, installation_id=body.installationId, event_id=body.eventId,
                attempt_id=body.attemptId, sequence=body.sequence, release_id=body.releaseId, artifact_id=body.artifactId,
                source_id=body.sourceId, source_revision=body.sourceRevision, policy_revision=body.policyRevision,
                stage=body.stage, from_version_code=body.fromVersionCode, target_version_code=body.targetVersionCode,
                observed_version_code=body.observedVersionCode, occurred_at=body.occurredAt, created_at=received,
                request_sha256=sha, error_code=body.errorCode))
            same = device.attempt_id == body.attemptId
            newer = not previous_attempt and (device.attempt_id is None or
                body.targetVersionCode >= device.observed.get("targetVersionCode", 0))
            advance = (same and body.sequence > device.last_sequence) or (not same and newer)
            # Terminal success cannot be rolled backwards by a mislabeled
            # higher sequence in the same attempt.
            if same and device.stage in ("healthy", "superseded"):
                advance = advance and body.stage in ("healthy", "superseded")
            if advance:
                device.attempt_id, device.last_sequence, device.stage = body.attemptId, body.sequence, body.stage
                device.last_policy_revision = max(device.last_policy_revision, body.policyRevision)
                device.current_version_code = max(device.current_version_code, body.observedVersionCode)
                device.observed = dict(device.observed) | dict(targetVersionCode=body.targetVersionCode,
                    releaseId=body.releaseId, artifactId=body.artifactId, observedVersionCode=body.observedVersionCode)
            return c.ReceiptResult(eventId=body.eventId, accepted=True, duplicate=False,
                receivedAt=received).model_dump(mode="json")

    def view(self, row, session=None):
        if isinstance(row, AppArtifact):
            resource_id, kind, state, revision = row.artifact_id, "artifact", row.state, 1
            details = dict(packageName=row.package_name, publisherId=row.publisher_id,
                versionCode=row.version_code, versionName=row.version_name, sizeBytes=row.size_bytes,
                sha256=row.sha256, signerSha256=row.signer_sha256, minSdk=row.min_sdk, abis=row.abis,
                serverContractRange=dict(min=row.server_contract_min, max=row.server_contract_max),
                dataSchemaVersion=row.data_schema_version,
                readableDataSchemaRange=dict(min=row.readable_schema_min, max=row.readable_schema_max),
                errorCode=row.error_code, verifiedAt=row.verified_at)
            if session is not None:
                jobs = session.scalars(select(AppUpload).where(or_(AppUpload.artifact_id == row.artifact_id,
                    AppUpload.target_artifact_id == row.artifact_id)).order_by(AppUpload.created_at.desc(),
                    AppUpload.upload_id.desc()).limit(10)).all()
                details["jobs"] = [dict(jobId=j.upload_id, kind=j.kind, state=j.state,
                    errorCode=j.error_code, resolvedArtifactId=j.resolved_artifact_id,
                    targetArtifactId=j.target_artifact_id, createdAt=aware(j.created_at)) for j in jobs]
        elif isinstance(row, AppRelease):
            resource_id, kind, state, revision = row.release_id, "release", row.state, 1
            details = dict(policyId=row.policy_id, artifactId=row.artifact_id, importance=row.importance,
                releasePurpose=row.purpose, notes=row.notes, publishedAt=row.published_at, stoppedAt=row.stopped_at)
            if session is not None:
                policy = session.get(AppPolicy, row.policy_id)
                revision = policy.revision
                details.update(publisherId=policy.publisher_id, packageName=policy.package_name,
                    channel=policy.channel, deploymentId=policy.deployment_id,
                    minSupportedVersionCode=policy.min_supported_version_code,
                    restrictedCapabilities=policy.restricted_capabilities,
                    sourceBinding=next((b for b in policy.selection.get("releases", [])
                                        if b["releaseId"] == row.release_id), None))
                details["rollbackOperationIds"] = [op.operation_id for op in session.scalars(select(AppRollback)
                    .where(AppRollback.policy_id == policy.policy_id).order_by(AppRollback.created_at.desc())
                    .limit(10)) if row.release_id in op.affected_release_ids or row.release_id == op.recovery_release_id]
        elif isinstance(row, AppArtifactSource):
            resource_id, kind, state, revision = row.source_id, "source", row.state, row.source_revision
            if state == "retired":
                state = "failed"
            # Raw URLs, object credentials, evidence paths are not exposed in
            # admin projections. MinIO presigned URLs exist only in signed tickets.
            details = dict(artifactId=row.artifact_id, storageMode=row.storage_mode, accessMode=row.access_mode,
                allowedDownloadHosts=row.allowed_hosts, sha256=row.verified_sha256,
                sizeBytes=row.verified_size_bytes, availabilityState=row.availability_state, sourceState=row.state)
        else:
            resource_id, kind, state, revision = row.audit_id, "audit", "verified", row.after_revision or 1
            details = dict(actorId=row.actor_id, action=row.action, resourceId=row.resource_id,
                reason=audit_text(row.reason), result=row.result, beforeRevision=row.before_revision, afterRevision=row.after_revision,
                artifactIds=row.details.get("artifactIds", []), sourceBindings=row.details.get("sourceBindings", []),
                errorCode=row.details.get("errorCode"))
        details["createdAt"] = aware(row.created_at)
        return c.ResourceView(resourceId=resource_id, resourceType=kind, state=state, revision=revision, details=details)

    def read(self, actor, kind, *, resource_id=None, artifact_id=None, limit=50, cursor=None):
        model, id_column = {"artifacts": (AppArtifact, AppArtifact.artifact_id),
            "releases": (AppRelease, AppRelease.release_id), "sources": (AppArtifactSource, AppArtifactSource.source_id),
            "audit": (AppAudit, AppAudit.audit_id)}[kind]
        with self.db.session() as session:
            self.authorize(session, actor)
            query = select(model)
            if resource_id:
                row = session.get(model, resource_id)
                if row is None:
                    raise UpdateError("release_not_found" if kind == "releases" else "artifact_not_verified")
                return self.view(row, session).model_dump(mode="json")
            if not 1 <= limit <= 100:
                raise UpdateError("invalid_request")
            if artifact_id:
                query = query.where(AppArtifactSource.artifact_id == artifact_id)
            if cursor:
                try:
                    if len(cursor) > 512:
                        raise ValueError()
                    position = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                    if position[0] != kind or position[1] != artifact_id:
                        raise ValueError()
                    timestamp, last_id = datetime.fromisoformat(position[2]), position[3]
                    anchor_query = select(model.created_at).where(id_column == last_id)
                    if artifact_id:
                        anchor_query = anchor_query.where(AppArtifactSource.artifact_id == artifact_id)
                    anchor = session.scalar(anchor_query)
                    if anchor is None or aware(anchor) != aware(timestamp):
                        raise ValueError()
                    # Compare database values to database values: legacy SQLite
                    # defaults omit fractional seconds whereas bound datetimes
                    # include them, so equal instants can compare differently.
                    point = anchor_query.scalar_subquery()
                    query = query.where(or_(model.created_at < point,
                        and_(model.created_at == point, id_column < last_id)))
                except (ValueError, TypeError, IndexError, KeyError):
                    raise UpdateError("invalid_request") from None
            rows = session.scalars(query.order_by(model.created_at.desc(), id_column.desc()).limit(limit + 1)).all()
            page, next_cursor = rows[:limit], None
            if len(rows) > limit:
                last = page[-1]
                next_cursor = base64.urlsafe_b64encode(json_bytes([kind, artifact_id, aware(last.created_at).isoformat(),
                    getattr(last, id_column.key)])).decode().rstrip("=")
            return c.ResourcePage(items=[self.view(row, session) for row in page], nextCursor=next_cursor).model_dump(mode="json")
