"""Read-only rollback planning and atomic forward recovery.

Recovery evidence is supplied by trusted deployment/CI configuration, never by
the administrator's browser. A reference alone does not prove compatibility.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from . import contract as c
from .models import (AppArtifact, AppArtifactSource, AppDeviceState,
                     AppRelease, AppRollback)
from .service import UpdateError, aware, digest, now
from .security import audit_text


def plan(service, session, identity, policy, body):
    blockers = []
    ids = body.affectedReleaseIds
    if len(set(ids)) != len(ids) or body.stableReleaseId in ids or body.recoveryReleaseId in [*ids, body.stableReleaseId]:
        raise UpdateError("invalid_request")
    affected = [service.release(session, policy, value) for value in ids]
    stable = service.release(session, policy, body.stableReleaseId)
    prior_pending = next((op for op in session.scalars(select(AppRollback).where(AppRollback.policy_id == policy.policy_id,
        AppRollback.recovery_state == "pending", AppRollback.state == "applied"))
        if set(op.affected_release_ids) == set(ids) and op.stable_release_id == body.stableReleaseId), None)
    if any(r.state != "published" and not (r.state == "stopped" and prior_pending
            and r.release_id in prior_pending.affected_release_ids) for r in affected):
        blockers.append("affected_release_not_active")
    if stable.state != "published" or stable.purpose != "normal":
        blockers.append("stable_release_not_active")
    bad = [service.artifact(session, identity, r.artifact_id) for r in affected]
    stable_apk = service.artifact(session, identity, stable.artifact_id)
    if any(a.version_code <= stable_apk.version_code for a in bad):
        blockers.append("stable_version_not_lower")
    if any(session.get(AppArtifact, b["artifactId"]).version_code > stable_apk.version_code
           for b in policy.selection.get("releases", []) if b["releaseId"] not in ids
           and b["releaseId"] != body.recoveryReleaseId):
        blockers.append("uncovered_newer_release")

    def bound(release, artifact):
        binding = next((b for b in policy.selection.get("releases", []) if b["releaseId"] == release.release_id), None)
        if binding is None and release.state == "draft":
            source = session.scalar(select(AppArtifactSource).where(AppArtifactSource.artifact_id == artifact.artifact_id,
                AppArtifactSource.state == "verified", AppArtifactSource.availability_state == "available")
                .order_by(AppArtifactSource.source_revision.desc()).limit(1))
            if source:
                binding = dict(releaseId=release.release_id, artifactId=artifact.artifact_id,
                    sourceId=source.source_id, sourceRevision=source.source_revision)
        if binding is None:
            raise UpdateError("source_not_verified")
        source = service.source(session, artifact, binding["sourceId"], binding["sourceRevision"])
        return binding, dict(state=source.state, hash=source.verified_sha256, size=source.verified_size_bytes,
            available=source.availability_state, hosts=source.allowed_hosts, urlDigest=digest(source.public_url),
            bucket=source.bucket, key=source.object_key, version=source.object_version_id, etag=source.object_etag,
            evidence=source.verification_evidence_ref)

    stable_binding, stable_source = bound(stable, stable_apk)
    recovery, recovery_apk, recovery_binding, recovery_source, evidence = None, None, None, None, None
    if body.recoveryReleaseId:
        recovery = service.release(session, policy, body.recoveryReleaseId)
        recovery_apk = service.artifact(session, identity, recovery.artifact_id)
        if recovery.state != "draft" or recovery.purpose != "normal":
            blockers.append("recovery_not_draft")
        if recovery_apk.version_code <= max(a.version_code for a in bad):
            blockers.append("recovery_version_not_higher")
        if (recovery_apk.data_schema_version < max(a.data_schema_version for a in bad)
                or any(not recovery_apk.readable_schema_min <= a.data_schema_version <= recovery_apk.readable_schema_max for a in bad)):
            blockers.append("recovery_data_incompatible")
        expected = dict(stableSha256=stable_apk.sha256, affectedSha256=sorted(a.sha256 for a in bad),
            recoverySha256=recovery_apk.sha256, preservesData=True, restoresStableBehavior=True,
            serverContractVersion=service.server_contract)
        evidence = next((item for item in service.recovery_evidence if all(item.get(k) == v for k, v in expected.items())
            and isinstance(item.get("evidenceRef"), str) and 0 < len(item["evidenceRef"]) <= 512), None)
        if not evidence:
            blockers.append("recovery_evidence_missing")
        recovery_binding, recovery_source = bound(recovery, recovery_apk)
    for a in [*bad, stable_apk, *([recovery_apk] if recovery_apk else [])]:
        if not a.server_contract_min <= service.server_contract <= a.server_contract_max or not a.build_provenance.get("compatibilityEvidenceRef"):
            blockers.append("build_compatibility_missing")
    devices = session.scalars(select(AppDeviceState).where(AppDeviceState.policy_id == policy.policy_id)).all()
    bad_codes = {a.version_code for a in bad}
    if recovery_apk:
        for d in devices:
            if d.current_version_code in bad_codes and (not d.observed.get("context")
                    or d.observed.get("contextVersionCode") != d.current_version_code
                    or not service.compatible(recovery_apk, d.observed["context"])):
                blockers.append("recovery_device_incompatible")
                break
        if (recovery_apk.min_sdk > min(a.min_sdk for a in bad)
                or not set().union(*(set(a.abis) for a in bad)) <= set(recovery_apk.abis)):
            blockers.append("recovery_device_incompatible")
    def apk(a):
        return {column: getattr(a, column) for column in ("artifact_id", "state", "version_code", "sha256", "size_bytes",
            "signer_sha256", "min_sdk", "abis", "server_contract_min", "server_contract_max", "data_schema_version",
            "readable_schema_min", "readable_schema_max", "verification_evidence_ref", "build_provenance")}
    fingerprint = dict(request=body.model_dump(include=set(c.RollbackPreviewRequest.model_fields)),
        policy=policy.selection, revision=policy.revision, floor=policy.min_supported_version_code,
        caps=policy.restricted_capabilities, affected=[apk(a) for a in bad], stable=apk(stable_apk),
        stableBinding=stable_binding, stableSource=stable_source, recovery=apk(recovery_apk) if recovery_apk else None,
        recoveryBinding=recovery_binding, recoverySource=recovery_source, evidence=evidence, blockers=sorted(set(blockers)))
    return dict(fingerprint=fingerprint, blockers=sorted(set(blockers)), affected=affected, bad_codes=bad_codes,
        stable_binding=stable_binding, recovery=recovery, recovery_binding=recovery_binding, evidence=evidence,
        devices=devices)


def fingerprint(service, value):
    # Deterministic across processes sharing the publisher key, bounded to the
    # current five-minute window. No preview rows or device writes are needed.
    expires = (int(now().timestamp()) // 300 + 1) * 300
    signature = service.publisher.sign(dict(messageType="rollback_preview", expiresAt=expires, plan=value))
    return digest(signature), datetime.fromtimestamp(expires, timezone.utc)


def preview(service, actor, body):
    with service.db.session() as session:
        identity = service.identity(session, body, readonly=True)
        service.authorize(session, actor)
        policy = service.policy(session, body)
        if policy.revision != body.expectedPolicyRevision:
            raise UpdateError("policy_revision_conflict")
        p = plan(service, session, identity, policy, body)
        token, expires = fingerprint(service, p["fingerprint"])
        return c.RollbackPreview(expectedPolicyRevision=policy.revision, previewFingerprint=token,
            expiresAt=expires, ready=not p["blockers"], blockers=p["blockers"],
            contactedDevices=len(p["devices"]), affectedDevices=sum(d.current_version_code in p["bad_codes"] for d in p["devices"]),
            recoveryState="ready" if body.recoveryReleaseId and not p["blockers"] else "pending").model_dump(mode="json")


def operation(service, session, row):
    bad = session.scalars(select(AppArtifact.version_code).join(AppRelease, AppRelease.artifact_id == AppArtifact.artifact_id)
        .where(AppRelease.release_id.in_(row.affected_release_ids))).all()
    recovery = session.get(AppRelease, row.recovery_release_id) if row.recovery_release_id else None
    target_code = session.get(AppArtifact, recovery.artifact_id).version_code if recovery else None
    devices = session.scalars(select(AppDeviceState).where(AppDeviceState.policy_id == row.policy_id)).all()
    counts = {}
    for d in devices:
        stage = None
        if d.current_version_code in bad:
            stage = d.stage if recovery and d.observed.get("releaseId") == recovery.release_id else "not_discovered"
        elif recovery and d.observed.get("releaseId") == recovery.release_id and d.observed.get("observedVersionCode") == target_code:
            stage = d.stage
        if stage:
            counts[stage] = counts.get(stage, 0) + 1
    # Unknown installations cannot be counted; never invent "uncontacted".
    return c.OperationResult(operationId=row.operation_id, status=row.state,
        effectivePolicyRevision=row.effective_policy_revision,
        recoveryState="pending" if recovery and recovery.state != "published" else row.recovery_state,
        deviceCounts=counts, lastContactBefore=max((aware(d.last_contact_at) for d in devices), default=None),
        errorCode=row.error_code).model_dump(mode="json")


def apply(service, actor, body):
    with service.db.session() as session:
        identity = service.identity(session, body)
        service.authorize(session, actor)
        policy = service.policy(session, body)
        prior = session.scalar(select(AppRollback).where(AppRollback.policy_id == policy.policy_id,
            AppRollback.idempotency_key == body.idempotencyKey))
        if prior:
            if prior.actor_id != actor or prior.request_sha256 != digest(body.model_dump(mode="json")):
                raise UpdateError("idempotency_conflict")
            return operation(service, session, prior)
        if policy.revision != body.expectedPolicyRevision:
            raise UpdateError("policy_revision_conflict")
        p = plan(service, session, identity, policy, body)
        if p["blockers"]:
            raise UpdateError("recovery_incompatible")
        if fingerprint(service, p["fingerprint"])[0] != body.previewFingerprint:
            raise UpdateError("rollback_preview_stale")
        for binding in [p["stable_binding"], *([p["recovery_binding"]] if p["recovery_binding"] else [])]:
            source = session.get(AppArtifactSource, binding["sourceId"])
            if source.storage_mode == "internal":
                issued = now()
                service.address(source, session.get(AppArtifact, binding["artifactId"]), issued, issued + timedelta(seconds=900))
        before = policy.revision
        row = AppRollback(policy_id=policy.policy_id, idempotency_key=body.idempotencyKey,
            request_sha256=digest(body.model_dump(mode="json")), preview_fingerprint=body.previewFingerprint,
            expected_policy_revision=before, affected_release_ids=body.affectedReleaseIds,
            stable_release_id=body.stableReleaseId, recovery_release_id=body.recoveryReleaseId,
            state="accepted", recovery_state="pending", reason=audit_text(body.reason), actor_id=actor)
        session.add(row)
        session.flush()
        for release in p["affected"]:
            release.state, release.stopped_at = "stopped", now()
        selection = dict(policy.selection)
        selection["releases"] = [p["stable_binding"]]
        selection["stoppedReleaseIds"] = list(dict.fromkeys([*selection.get("stoppedReleaseIds", []), *body.affectedReleaseIds]))
        pending = set(selection.get("recoveryPendingVersionCodes", [])) | p["bad_codes"]
        if p["recovery"]:
            recovery = p["recovery"]
            recovery.state, recovery.purpose, recovery.published_at = "published", "recovery", now()
            recovery.recovery_evidence_ref = p["evidence"]["evidenceRef"]
            row.recovery_evidence_ref = recovery.recovery_evidence_ref
            row.recovery_state = "ready"
            selection["releases"].append(p["recovery_binding"])
            # Binding is per release so later recovery operations cannot relabel
            # an older package with another operation's provenance.
            selection["recoveryBindings"] = {**selection.get("recoveryBindings", {}), recovery.release_id: dict(
                rollbackOperationId=row.operation_id, restoresBehaviorFromReleaseId=body.stableReleaseId,
                affectedReleaseIds=body.affectedReleaseIds)}
            selection["recoveryVersionCodes"] = {**selection.get("recoveryVersionCodes", {}), recovery.release_id: sorted(p["bad_codes"])}
            pending -= p["bad_codes"]
        selection["recoveryPendingVersionCodes"] = sorted(pending)
        policy.min_supported_version_code, policy.restricted_capabilities = 1, []
        session.flush()
        service.snapshot(session, actor, policy, body, before, selection)
        row.state, row.applied_at, row.effective_policy_revision = "applied", now(), policy.revision
        service.audit(session, actor, "app_rollback", body, policy,
            dict(resourceId=row.operation_id, state="published", revision=policy.revision), before)
        session.flush()
        return operation(service, session, row)


def read(service, actor, operation_id):
    with service.db.session() as session:
        service.authorize(session, actor)
        row = session.get(AppRollback, operation_id)
        if row is None:
            raise UpdateError("release_not_found")
        return operation(service, session, row)
