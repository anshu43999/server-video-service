"""Frozen app-update/v1 wire types, shared by M42 and Android M118.

These types define a contract; HTTP handlers and APK verification follow in
M42-T02..T08. JSON schema is exported in docs/app-update-v1.schema.json.
"""
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "app-update/v1"
PACKAGE_NAME = "com.aiyolo.inspection"
FIRST_VERSION_CODE = 1
# Phase 1 uses Android versionCode with versionCodeMajor=0. Compare as Long
# on Android; versionName is display-only. A major-code extension needs v2.
MAX_VERSION_CODE = 2147483647
SIGNATURE_DOMAIN = b"AIYOLO-APP-UPDATE/v1\x00"
MAX_METADATA_BYTES = 262144

Id = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[int, Field(ge=1, le=MAX_VERSION_CODE)]
Revision = Annotated[int, Field(ge=1, le=MAX_VERSION_CODE)]
Size = Annotated[int, Field(ge=1, le=8589934592)]
Abi = Literal["arm64-v8a", "armeabi-v7a", "x86", "x86_64"]
Stage = Literal["discovered", "downloading", "downloaded", "verified", "waiting_install",
                "installer_opened", "started_pending_health", "healthy", "failed", "canceled", "superseded"]


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Scope(Wire):
    contractVersion: Literal["app-update/v1"]
    publisherId: Id
    packageName: Literal["com.aiyolo.inspection"]
    channel: Id
    deploymentId: Id


class ClientContext(Scope):
    requestId: Id
    installationId: Id
    currentVersionCode: Version


class CheckRequest(ClientContext):
    currentVersionName: Annotated[str, Field(min_length=1, max_length=128)]
    sdkInt: Annotated[int, Field(ge=27, le=10000)]
    supportedAbis: Annotated[list[Abi], Field(min_length=1, max_length=4)]
    signerSha256: Digest
    serverContractVersion: Revision
    lastPolicyRevision: Annotated[int, Field(ge=0, le=MAX_VERSION_CODE)]


class ContractRange(Wire):
    min: Revision
    max: Revision

    @model_validator(mode="after")
    def ordered(self):
        if self.min > self.max:
            raise ValueError("invalid server contract range")
        return self


class Compatibility(Wire):
    minSupportedVersionCode: Version
    onlineAction: Literal["allow", "restrict_declared_capabilities"]
    restrictedCapabilities: Annotated[list[Id], Field(max_length=32)]
    reasonCode: Annotated[str | None, Field(max_length=128)]

    @model_validator(mode="after")
    def declared_gate(self):
        restricted = self.onlineAction == "restrict_declared_capabilities"
        if restricted != bool(self.restrictedCapabilities) or (restricted and not self.reasonCode):
            raise ValueError("compatibility gate requires explicit capabilities and reason")
        return self


class Target(Wire):
    releaseId: Id
    artifactId: Id
    sourceId: Id
    sourceRevision: Revision
    versionCode: Version
    versionName: Annotated[str, Field(min_length=1, max_length=128)]
    sizeBytes: Size
    sha256: Digest
    signerSha256: Digest
    minSdk: Annotated[int, Field(ge=27, le=10000)]
    abis: Annotated[list[Abi], Field(min_length=1, max_length=4)]
    serverContractRange: ContractRange
    dataSchemaVersion: Revision
    readableDataSchemaRange: ContractRange
    publishedAt: AwareDatetime
    notes: Annotated[list[Annotated[str, Field(min_length=1, max_length=2000)]], Field(max_length=30)]
    importance: Literal["normal", "important"]
    releasePurpose: Literal["normal", "recovery"]
    rollbackOperationId: Id | None
    restoresBehaviorFromReleaseId: Id | None
    affectedReleaseIds: Annotated[list[Id], Field(max_length=100)]

    @model_validator(mode="after")
    def recovery_binding(self):
        complete = bool(self.rollbackOperationId and self.restoresBehaviorFromReleaseId and self.affectedReleaseIds)
        empty = not (self.rollbackOperationId or self.restoresBehaviorFromReleaseId or self.affectedReleaseIds)
        if (self.releasePurpose == "recovery" and not complete) or (self.releasePurpose == "normal" and not empty):
            raise ValueError("release purpose and recovery references disagree")
        if not self.readableDataSchemaRange.min <= self.dataSchemaVersion <= self.readableDataSchemaRange.max:
            raise ValueError("artifact must read its own data schema")
        return self


class SignedPayload(ClientContext):
    policyRevision: Revision
    issuedAt: AwareDatetime
    authorizationExpiresAt: AwareDatetime

    @model_validator(mode="after")
    def bounded_lifetime(self):
        seconds = (self.authorizationExpiresAt - self.issuedAt).total_seconds()
        maximum = 120 if isinstance(self, InstallPermissionPayload) else 900
        if not 0 < seconds <= maximum:
            raise ValueError("invalid authorization lifetime")
        return self


class CheckPayload(SignedPayload):
    messageType: Literal["check"]
    result: Literal["up_to_date", "update_available", "no_compatible_release", "client_unsupported", "recovery_pending"]
    release: Target | None
    compatibility: Compatibility

    @model_validator(mode="after")
    def actionable_target(self):
        if (self.result == "update_available") != (self.release is not None):
            raise ValueError("only update_available contains an installable target")
        if self.release:
            if self.release.versionCode <= self.currentVersionCode:
                raise ValueError("APK replacement must increase versionCode")
            if self.compatibility.minSupportedVersionCode > self.release.versionCode:
                raise ValueError("compatibility floor exceeds available target")
        return self


class ArtifactBinding(ClientContext):
    expectedPolicyRevision: Revision
    releaseId: Id
    artifactId: Id
    sourceId: Id
    sourceRevision: Revision
    sha256: Digest
    sizeBytes: Size


class DownloadRequest(ArtifactBinding):
    pass


class InstallPermissionRequest(ArtifactBinding):
    verifiedVersionCode: Version
    verifiedSignerSha256: Digest

    @model_validator(mode="after")
    def increasing(self):
        if self.verifiedVersionCode <= self.currentVersionCode:
            raise ValueError("APK downgrade is forbidden")
        return self


class DownloadPayload(SignedPayload):
    messageType: Literal["download"]
    releaseId: Id
    artifactId: Id
    sourceId: Id
    sourceRevision: Revision
    versionCode: Version
    sha256: Digest
    sizeBytes: Size
    signerSha256: Digest
    storageMode: Literal["internal", "external"]
    accessMode: Literal["public", "presigned"]
    downloadUrl: Annotated[str, Field(min_length=1, max_length=4096)]
    downloadUrlExpiresAt: AwareDatetime | None
    allowedDownloadHosts: Annotated[list[Id], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def direct_https(self):
        parsed = urlsplit(self.downloadUrl)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("APK source must be credential-free HTTPS")
        if parsed.hostname not in self.allowedDownloadHosts:
            raise ValueError("download host is not approved")
        if self.storageMode == "external" and self.accessMode != "public":
            raise ValueError("phase 1 external sources must be public")
        if (self.accessMode == "public") != (self.downloadUrlExpiresAt is None):
            raise ValueError("public links have no file URL expiry")
        if self.downloadUrlExpiresAt and self.downloadUrlExpiresAt < self.authorizationExpiresAt:
            raise ValueError("URL expires before download authorization")
        if self.versionCode <= self.currentVersionCode:
            raise ValueError("APK downgrade is forbidden")
        return self


class InstallPermissionPayload(SignedPayload):
    messageType: Literal["install_permission"]
    permissionId: Id
    releaseId: Id
    artifactId: Id
    sourceId: Id
    sourceRevision: Revision
    versionCode: Version
    sha256: Digest
    sizeBytes: Size
    signerSha256: Digest
    userActionRequired: Literal[True]
    offlineInstallAllowed: Literal[False]

    @model_validator(mode="after")
    def increasing(self):
        if self.versionCode <= self.currentVersionCode:
            raise ValueError("APK downgrade is forbidden")
        return self


class SignedEnvelope(Wire):
    keyId: Id
    payloadBase64Url: Annotated[str, Field(min_length=1, max_length=349526, pattern=r"^[A-Za-z0-9_-]+$")]
    signatureBase64Url: Annotated[str, Field(min_length=86, max_length=86, pattern=r"^[A-Za-z0-9_-]+$")]


class Receipt(ClientContext):
    eventId: Id
    attemptId: Id
    sequence: Revision
    policyRevision: Revision
    releaseId: Id
    artifactId: Id
    sourceId: Id | None
    sourceRevision: Revision | None
    stage: Stage
    fromVersionCode: Version
    targetVersionCode: Version
    observedVersionCode: Version
    occurredAt: AwareDatetime
    errorCode: Id | None

    @model_validator(mode="after")
    def truthful_stage(self):
        if self.targetVersionCode <= self.fromVersionCode:
            raise ValueError("receipt target must increase")
        if (self.sourceId is None) != (self.sourceRevision is None):
            raise ValueError("source identity and revision are a pair")
        if self.stage in ("started_pending_health", "healthy") and self.observedVersionCode != self.targetVersionCode:
            raise ValueError("startup and health require exact observed target version")
        if self.stage == "superseded" and self.observedVersionCode <= self.targetVersionCode:
            raise ValueError("superseded requires a later installed version")
        if self.stage == "failed" and not self.errorCode:
            raise ValueError("failure requires an error code")
        return self


class ReceiptResult(Wire):
    eventId: Id
    accepted: Literal[True]
    duplicate: bool
    receivedAt: AwareDatetime


class Mutation(Wire):
    idempotencyKey: Id
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class ExternalArtifactRequest(Mutation):
    packageName: Literal["com.aiyolo.inspection"]
    downloadUrl: Annotated[str, Field(min_length=1, max_length=4096)]
    allowedDownloadHosts: Annotated[list[Id], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def direct_https(self):
        parsed = urlsplit(self.downloadUrl)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.hostname not in self.allowedDownloadHosts):
            raise ValueError("APK source must be approved credential-free HTTPS")
        return self


class SourceRequest(ExternalArtifactRequest):
    expectedArtifactSha256: Digest


class ReleaseDraftRequest(Scope, Mutation):
    artifactId: Id
    importance: Literal["normal", "important"]
    notes: Annotated[list[Annotated[str, Field(min_length=1, max_length=2000)]], Field(max_length=30)]


class PolicyMutation(Scope, Mutation):
    expectedPolicyRevision: Revision


class PublishRequest(PolicyMutation):
    releaseId: Id
    sourceId: Id
    sourceRevision: Revision
    minSupportedVersionCode: Version
    restrictedCapabilities: Annotated[list[Id], Field(max_length=32)]


class StopRequest(PolicyMutation):
    releaseId: Id


class RollbackPreviewRequest(Scope):
    expectedPolicyRevision: Revision
    affectedReleaseIds: Annotated[list[Id], Field(min_length=1, max_length=100)]
    stableReleaseId: Id
    recoveryReleaseId: Id | None


class RollbackRequest(RollbackPreviewRequest, Mutation):
    previewFingerprint: Digest


class RollbackPreview(Wire):
    expectedPolicyRevision: Revision
    previewFingerprint: Digest
    expiresAt: AwareDatetime
    ready: bool
    blockers: Annotated[list[Id], Field(max_length=100)]
    contactedDevices: Annotated[int, Field(ge=0)]
    affectedDevices: Annotated[int, Field(ge=0)]
    recoveryState: Literal["ready", "pending"]


class OperationResult(Wire):
    operationId: Id
    status: Literal["accepted", "applied", "failed"]
    effectivePolicyRevision: Revision | None
    recoveryState: Literal["ready", "pending"]
    deviceCounts: dict[Literal[Stage, "not_discovered", "uncontacted"], Annotated[int, Field(ge=0)]]
    lastContactBefore: AwareDatetime | None
    errorCode: Id | None


class ResourceResult(Wire):
    resourceId: Id
    state: Literal["pending", "verifying", "verified", "failed", "draft", "published", "stopped"]
    revision: Revision


class ResourceView(ResourceResult):
    resourceType: Literal["artifact", "source", "release", "policy", "audit"]
    # Details use one of the frozen domain records. This admin-only projection
    # is extensible; clients cannot treat it as mobile install authorization.
    details: dict


class ResourcePage(Wire):
    items: Annotated[list[ResourceView], Field(max_length=100)]
    nextCursor: Annotated[str | None, Field(max_length=512)]


# Error bodies are unsigned and can never authorize download/install or imply
# up_to_date. The boolean tells clients whether bounded retry is appropriate.
ERRORS = {
    "invalid_request": (422, False), "contract_unsupported": (426, False),
    "deployment_not_allowed": (403, False), "authentication_required": (401, False),
    "platform_admin_required": (403, False), "release_not_found": (404, False),
    "release_stopped": (410, False), "artifact_not_verified": (409, False),
    "source_not_verified": (409, False), "source_revision_conflict": (409, True),
    "policy_revision_conflict": (409, True), "idempotency_conflict": (409, False),
    "version_not_increasing": (409, False), "signer_not_approved": (409, False),
    "compatibility_gate_unreachable": (409, False), "rollback_preview_stale": (409, True),
    "recovery_incompatible": (409, False), "source_unavailable": (503, True),
    "rate_limited": (429, True), "service_unavailable": (503, True),
}


class ErrorBody(Wire):
    code: Literal[tuple(ERRORS)]
    message: Annotated[str, Field(min_length=1, max_length=1000)]
    requestId: Id
    retryable: bool

    @model_validator(mode="after")
    def known_retry(self):
        if self.retryable != ERRORS[self.code][1]:
            raise ValueError("error retry behavior is fixed by contract")
        return self


TYPES = [CheckRequest, CheckPayload, DownloadRequest, DownloadPayload, InstallPermissionRequest,
         InstallPermissionPayload, SignedEnvelope, Receipt, ReceiptResult, ExternalArtifactRequest,
         SourceRequest, ReleaseDraftRequest, PublishRequest, StopRequest, RollbackPreviewRequest,
         RollbackRequest, RollbackPreview, OperationResult, ResourceResult, ResourceView, ResourcePage, ErrorBody]

# POST responses for check/download/install are SignedEnvelope; their decoded
# payload type is specified here and never sent as an unsigned sibling field.
API = [
    ("POST", "/mobile/app-updates/check", "CheckRequest", "CheckPayload", "deployment"),
    ("POST", "/mobile/app-updates/{releaseId}/download-ticket", "DownloadRequest", "DownloadPayload", "deployment"),
    ("POST", "/mobile/app-updates/{releaseId}/install-permission", "InstallPermissionRequest", "InstallPermissionPayload", "deployment"),
    ("POST", "/mobile/app-updates/receipts", "Receipt", "ReceiptResult", "deployment"),
    ("POST", "/admin/app-updates/artifacts/upload", "multipart:apk,idempotencyKey,reason", "ResourceResult", "PLATFORM_ADMIN"),
    ("POST", "/admin/app-updates/external-artifacts", "ExternalArtifactRequest", "ResourceResult", "PLATFORM_ADMIN"),
    ("POST", "/admin/app-updates/artifacts/{artifactId}/download-sources", "SourceRequest", "ResourceResult", "PLATFORM_ADMIN"),
    ("POST", "/admin/app-updates/releases", "ReleaseDraftRequest", "ResourceResult", "PLATFORM_ADMIN"),
    ("POST", "/admin/app-updates/releases/{releaseId}/publish", "PublishRequest", "ResourceResult", "PLATFORM_ADMIN"),
    ("POST", "/admin/app-updates/releases/{releaseId}/stop", "StopRequest", "ResourceResult", "PLATFORM_ADMIN"),
    ("POST", "/admin/app-updates/rollback-preview", "RollbackPreviewRequest", "RollbackPreview", "PLATFORM_ADMIN"),
    ("POST", "/admin/app-updates/rollbacks", "RollbackRequest", "OperationResult", "PLATFORM_ADMIN"),
    ("GET", "/admin/app-updates/rollbacks/{operationId}", None, "OperationResult", "PLATFORM_ADMIN"),
    ("GET", "/admin/app-updates/artifacts", None, "ResourcePage", "PLATFORM_ADMIN"),
    ("GET", "/admin/app-updates/artifacts/{artifactId}", None, "ResourceView", "PLATFORM_ADMIN"),
    ("GET", "/admin/app-updates/releases", None, "ResourcePage", "PLATFORM_ADMIN"),
    ("GET", "/admin/app-updates/releases/{releaseId}", None, "ResourceView", "PLATFORM_ADMIN"),
    ("GET", "/admin/app-updates/artifacts/{artifactId}/download-sources", None, "ResourcePage", "PLATFORM_ADMIN"),
    ("GET", "/admin/app-updates/audit", None, "ResourcePage", "PLATFORM_ADMIN"),
]


def schema_document():
    from pydantic.json_schema import models_json_schema
    _, result = models_json_schema([(model, "validation") for model in TYPES])
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **result,
            "title": CONTRACT_VERSION, "x-api-prefix": "/aiyoloapi",
            "x-api": [dict(method=m, path="/aiyoloapi" + p, request=q, response=r, auth=a)
                      for m, p, q, r, a in API],
            "x-errors": {key: dict(status=value[0], retryable=value[1]) for key, value in ERRORS.items()}}
