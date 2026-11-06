from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from anyio import CancelScope
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .stream import StreamSession
from .protocol import ERROR_CODES, InputRateLimitError, StreamState
from .auth import (
    SESSION_COOKIE,
    ROLE_ADMIN,
    authenticate,
    authentication_error,
    create_auth_router,
    require_admin,
    require_catalog_access,
    require_mobile,
)
from . import auth
from .model_removal import ModelRemoval
from .resource_lifecycle import deletion_headers
from sqlalchemy.exc import SQLAlchemyError
from .project_management import create_project_management_router
from .service_principals import (
    ServicePrincipal, STREAMS_INGEST, ALERTS_INGEST, create_service_principal_router,
    require_alert_ingest, assert_ingest_envelope, resolve_ingest_context,
    audit_ingest, ingest_write_guard,
)
from .project_auth import (
    PLATFORM_PROJECTS_MANAGE,
    PLATFORM_OBSERVABILITY_READ,
    PLATFORM_MODELS_MANAGE,
    PROJECT_READ,
    PROJECT_AUDIT_READ,
    PROJECT_RULES_MANAGE,
    PROJECT_INSPECTION_USE,
    PROJECT_ALERTS_DISPOSE,
    PROJECT_ALERTS_READ,
    PROJECT_EXPORTS_CREATE,
    PROJECT_MODELS_ASSIGN,
    PROJECT_SCENES_MANAGE,
    PROJECT_SETTINGS_MANAGE,
    PROJECT_STREAMS_MANAGE,
    PROJECT_STREAMS_VIEW,
    PROJECT_ACTIVE,
    ProjectContext,
    require_project_capability,
    require_platform_capability,
    resolve_websocket_project_context,
    resolve_project_context,
    _audit_platform_entry,
    _project_id,
    project_context_required_error,
)
from .config import settings
from .admin_frontend import mount_admin_frontend
from .database import DEFAULT_PROJECT_ID, database
from .app_updates.upload_api import configured_uploads, create_upload_router
from .app_updates.uploads import UploadError
from .app_updates.external_api import configured_external, create_external_router
from .app_updates.api import configured_updates, create_update_router
from .alert_advice_knowledge import AlertAdviceKnowledgeStore
from .alert_advice_api import create_alert_advice_router
from .alert_advice_generation import AlertAdviceGenerationStore, create_alert_advice_generation_router
from .alert_advice_service import AlertAdviceService, MockAdviceGenerator, MockKnowledgeRetriever
from .stream_config import (
    StreamConfiguration,
    StreamConfigConflict,
    StreamConfigNotFound,
    StreamConfigStore,
    infer_source_type,
    redact_source_url,
)
from .metrics import system_metrics
from .dashboard import DashboardStatsService
from .model_catalog import ModelCatalog
from .model_signing import ModelManifestSigner
from .model_parameters import ModelParameterConflict, ModelParameterError, ModelParameterStore
from .conversion import ConversionService
from .conversion_api import create_conversion_router
from .calibration import CalibrationDatasetCatalog
from .alerts.rules import RuleConflict, RuleValidationError, rule_registry
from .alerts.disposition import alert_disposition_store, public_alert_event as _public_alert_event
from .alerts.verification import AlertVerificationStore, alert_verification_store
from .project_delivery_policy import DeliveryPolicyConflict
from .project_business import model_assignments, audit_change
from .project_model_assignments import AssignmentConflict, ProjectModelAssignments
from .project_scenes import ProjectScenes, ScenePlanResolution, create_scene_router
from .project_model_policy import project_target_usable
from .alerts.delivery import AlertDeliveryService
from .alerts.runtime import ServerAlertRuntime
from .alert_evidence import AlertEvidenceStore, EvidenceStorageError
from .media_authorization import create_media_authorization_router
from .model_updates.api import create_router as create_model_update_router
from .model_updates.service import ModelUpdateService

class ProjectStreamRegistry(dict[tuple[str, str], StreamSession]):
    @staticmethod
    def _key(key):
        return (DEFAULT_PROJECT_ID, key) if isinstance(key, str) else key

    def __getitem__(self, key):
        return super().__getitem__(self._key(key))

    def __setitem__(self, key, value):
        return super().__setitem__(self._key(key), value)

    def __contains__(self, key):
        return super().__contains__(self._key(key))

    def get(self, key, default=None):
        return super().get(self._key(key), default)

    def pop(self, key, default=None):
        return super().pop(self._key(key), default)


streams = ProjectStreamRegistry()
stream_config_store = StreamConfigStore(database if database.enabled else None)
stream_restore_errors: dict[tuple[str, str], str] = {}
model_catalog = ModelCatalog()
model_parameter_store = ModelParameterStore(database_manager=database if database.enabled else None)
project_model_assignments = ProjectModelAssignments(
    database, model_catalog, model_parameter_store, stream_config_store)
project_scenes = ProjectScenes(database, model_catalog, project_model_assignments)
model_updates = ModelUpdateService(database, model_catalog, project_scenes)
conversion_service = ConversionService(
    model_catalog.project_root / "models" / "local-conversion",
    database_manager=database if database.enabled else None,
)
calibration_catalog = CalibrationDatasetCatalog(
    Path(settings.calibration_root),
    database if database.enabled else None,
    max_expanded_bytes=settings.calibration_max_expanded_bytes,
    max_files=settings.calibration_max_files,
)
alert_verification_store.configure_database(database if database.enabled else None)
alert_verification_store.configure_provider(None)
alert_delivery = AlertDeliveryService(database_manager=database if database.enabled else None)
alert_evidence_store = AlertEvidenceStore.from_settings(settings)
server_alert_runtime = ServerAlertRuntime(
    model_provider=lambda model_id, version=None: model_catalog.get(model_id, version),
    parameter_store=model_parameter_store,
    event_store=alert_disposition_store,
    delivery_service=alert_delivery,
    evidence_root=model_catalog.project_root / "evidence" / "server-alerts",
    evidence_store=alert_evidence_store,
    profile_provider=lambda project_id, source_id, model_id: _runtime_profile(project_id, source_id, model_id),
)
dashboard_stats = DashboardStatsService(
    database if database.enabled else None,
    alert_disposition_store,
    alert_verification_store,
)

# Download guardrails are process-local by design.  A deployment with multiple
# workers should enforce the same limits at its ingress/proxy as well; these
# counters still protect each worker from unbounded file handles and bandwidth.
_download_lock = threading.Lock()
_download_active = 0
_download_rate_events: dict[str, deque[float]] = defaultdict(deque)


def _acquire_model_download(request: Request) -> None:
    """Reserve one download slot and consume one client rate-limit token."""
    global _download_active
    now = time.monotonic()
    key = request.client.host if request.client else "unknown"
    with _download_lock:
        max_concurrent = max(1, int(settings.model_download_max_concurrent))
        if _download_active >= max_concurrent:
            raise HTTPException(
                status_code=429,
                detail={"error": {"code": "rate_limited", "message": "download concurrency limit reached", "retryable": True}},
                headers={"Retry-After": "1"},
            )
        events = _download_rate_events[key]
        window = max(1.0, float(settings.model_download_rate_window_seconds))
        while events and now - events[0] >= window:
            events.popleft()
        rate_limit = int(settings.model_download_rate_limit)
        if rate_limit > 0 and len(events) >= rate_limit:
            retry_after = max(1, int(window - (now - events[0]) + 0.999))
            raise HTTPException(
                status_code=429,
                detail={"error": {"code": "rate_limited", "message": "download rate limit exceeded", "retryable": True}},
                headers={"Retry-After": str(retry_after)},
            )
        events.append(now)
        _download_active += 1


def _release_model_download() -> None:
    global _download_active
    with _download_lock:
        _download_active = max(0, _download_active - 1)


class CreateStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    stream_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    source_url: str | int | None = None
    scene_id: str = Field(alias="sceneId", min_length=1, max_length=128)
    plan_id: str = Field(alias="planId", min_length=1, max_length=128)
    scene_revision: int = Field(alias="sceneRevision", ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    source_type: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    enabled: bool = True


class ModelLifecycleRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class ModelPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: list[Literal["pc", "mobile"]] = Field(min_length=1, max_length=2)
    licenseApproved: Literal[True]
    reason: str = Field(min_length=1, max_length=512)


class ProjectModelAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modelId: str = Field(min_length=1, max_length=128)
    modelVersion: str = Field(min_length=1, max_length=128)
    target: Literal["pc", "mobile"]
    parameterRevision: int = Field(ge=0)
    enabled: bool
    expectedRevision: int = Field(ge=0)


class ModelMigrationRequest(BaseModel):
    targetModelId: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    version: str = Field(min_length=1, max_length=50)
    reason: str | None = Field(default=None, max_length=512)


class YoloRequest(BaseModel):
    enabled: bool


class StreamConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    confidence: float | None = Field(default=None, ge=0.01, le=0.99)
    max_fps: float | None = Field(default=None, ge=1, le=60)
    yolo_enabled: bool | None = None
    overlay_enabled: bool | None = None
    scene_id: str | None = Field(default=None, alias="sceneId", min_length=1, max_length=128)
    plan_id: str | None = Field(default=None, alias="planId", min_length=1, max_length=128)
    scene_revision: int | None = Field(default=None, alias="sceneRevision", ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None


class StreamModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    scene_id: str = Field(alias="sceneId", min_length=1, max_length=128)
    plan_id: str = Field(alias="planId", min_length=1, max_length=128)
    scene_revision: int = Field(alias="sceneRevision", ge=1)


class RegisterManifestRequest(BaseModel):
    manifest_path: str = Field(min_length=1, max_length=512)


class DetectionParameterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidenceThreshold: float = Field(ge=0.01, le=0.99)
    iouThreshold: float = Field(ge=0.10, le=0.90)
    maxDetections: int = Field(ge=1, le=300)


class ImageAlertParameterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimumConfidence: float = Field(ge=0.01, le=0.99)
    cooldownMs: int = Field(ge=0, le=86400000)


class CameraAlertParameterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimumConfidence: float = Field(ge=0.01, le=0.99)
    minimumConsecutiveFrames: int = Field(ge=1, le=120)
    minimumDwellTimeMs: int = Field(ge=0, le=600000)
    cooldownMs: int = Field(ge=0, le=86400000)


class AlertRuleParameterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rawLabel: str = Field(min_length=1, max_length=128)
    displayName: str = Field(min_length=1, max_length=80)
    eventCode: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]+$")
    operator: Literal["PRESENCE"] = "PRESENCE"
    enabled: bool
    severity: Literal["MINOR", "MAJOR", "CRITICAL"]
    image: ImageAlertParameterRequest | None = None
    camera: CameraAlertParameterRequest | None = None
    # Legacy v1 fields remain accepted while clients migrate to scene-specific fields.
    minimumConfidence: float | None = Field(default=None, ge=0.01, le=0.99)
    minimumConsecutiveFrames: int | None = Field(default=None, ge=1, le=120)
    minimumDwellTimeMs: int | None = Field(default=None, ge=0, le=600000)
    cooldownMs: int | None = Field(default=None, ge=0, le=86400000)


class ModelParameterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: int | None = Field(default=None, ge=1)
    expectedRevision: int | None = Field(default=None, ge=0)
    detection: DetectionParameterRequest
    alertRules: list[AlertRuleParameterRequest]


class RuleRequest(BaseModel):
    expectedRevision: int | None = Field(default=None, ge=0)
    ruleId: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    enabled: bool = True
    subjectKind: str = "track"
    operator: str
    requires: list[str] = Field(default_factory=list)
    targetLabels: list[str] = Field(default_factory=list)
    roiId: str | None = None
    roi: dict | None = None
    thresholds: dict = Field(default_factory=dict)
    severityBands: list[dict] = Field(default_factory=list)
    escalation: dict | None = None
    scope: dict | None = None


class RuleBindingRequest(BaseModel):
    expectedRevision: int | None = Field(default=None, ge=1)
    sourceId: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list)
    modelId: str | None = None


class AlertDispositionRequest(BaseModel):
    """Human disposition payload; actor is derived from the authenticated principal."""
    actedAtUs: int | None = Field(default=None, ge=0)
    screenshot: str | None = Field(default=None, max_length=2048)
    evidence: dict | None = None
    effectiveThresholds: dict | None = None
    detectionResults: list | dict | None = None
    note: str | None = Field(default=None, max_length=1000)
    expectedRevision: StrictInt | None = Field(default=None, ge=0)


class MobileAlertDispositionRequest(BaseModel):
    """A local App action; actor is a deprecated, ignored compatibility field."""

    status: Literal["ACKNOWLEDGED", "FALSE_POSITIVE"]
    actor: str | None = Field(default=None, min_length=1, max_length=128)
    actedAtUs: int = Field(ge=0)
    screenshot: str | None = Field(default=None, max_length=8_000_000)
    note: str | None = Field(default=None, max_length=1000)


class MobileAlertDispositionDeltaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operationId: str = Field(min_length=36, max_length=36)
    status: Literal["ACKNOWLEDGED", "FALSE_POSITIVE"]
    actedAtUs: int = Field(ge=0)
    expectedRevision: StrictInt | None = Field(default=None, ge=0)
    evidenceUnavailableReason: Literal[
        "no_local_capture", "local_file_missing", "upload_not_permitted", "capture_failed"
    ] | None = None


class AlertModelSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    modelId: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    version: str = Field(min_length=1, max_length=128)


class AlertSceneSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sceneId: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    revision: StrictInt = Field(ge=1)


class AlertPlanSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    planId: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)


class AlertProvenanceSnapshot(BaseModel):
    """Producer's historical display snapshot, never an authorization claim."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["SCENE", "STANDALONE"]
    model: AlertModelSnapshot
    scene: AlertSceneSnapshot | None = None
    plan: AlertPlanSnapshot | None = None
    memberId: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def coherent_source(self):
        if self.kind == "SCENE" and not (self.scene and self.plan and self.memberId):
            raise ValueError("scene provenance requires scene, plan and memberId")
        if self.kind == "STANDALONE" and any((self.scene, self.plan, self.memberId)):
            raise ValueError("standalone provenance cannot declare a scene")
        return self


class MobileAlertIngestRequest(BaseModel):
    """Portable event envelope produced by the Android local alert pipeline."""
    model_config = ConfigDict(extra="forbid")

    projectId: str | None = Field(default=None, min_length=1, max_length=36)

    eventId: str = Field(min_length=1, max_length=256, pattern=r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
    ruleId: str = Field(min_length=1, max_length=128)
    sourceId: str = Field(min_length=1, max_length=128)
    origin: Literal["MOBILE_CAMERA", "MOBILE_IMAGE"] | None = None
    provenance: AlertProvenanceSnapshot | None = None
    subjectKey: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=256)
    state: str = Field(min_length=1, max_length=32)
    severity: str = Field(default="MINOR", min_length=1, max_length=32)
    notifySeverity: str = Field(default="MINOR", min_length=1, max_length=32)
    startedAtUs: int = Field(ge=0)
    confirmedAtUs: int | None = Field(default=None, ge=0)
    lastSeenAtUs: int = Field(ge=0)
    effectiveThresholds: dict[str, Any] = Field(default_factory=dict)
    detectionResults: list | dict[str, Any] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    disposition: MobileAlertDispositionRequest | None = None


class DeliveryPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=0)
    enabled: bool
    channels: list[Literal["management", "app", "email", "sms", "enterprise_im"]]
    minimumSeverity: Literal["MINOR", "MAJOR", "CRITICAL"] = "MINOR"


class RuleValidationRequest(BaseModel):
    sourceId: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list)
    modelId: str | None = None


class RulePatchRequest(BaseModel):
    expectedRevision: int | None = Field(default=None, ge=1)
    name: str | None = None
    enabled: bool | None = None
    subjectKind: str | None = None
    operator: str | None = None
    requires: list[str] | None = None
    targetLabels: list[str] | None = None
    roiId: str | None = None
    roi: dict | None = None
    thresholds: dict | None = None
    severityBands: list[dict] | None = None
    escalation: dict | None = None
    scope: dict | None = None


class AlertDeliveryRequest(BaseModel):
    event: dict
    channels: list[str] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    # The registry is the single source of truth for model assets. Refuse to
    # start when an artifact is missing or changed; never silently fall back.
    await asyncio.to_thread(database.verify_schema)
    await asyncio.to_thread(_model_removal().recover)
    model_catalog.validate_startup()
    await asyncio.to_thread(alert_evidence_store.validate)
    await model_updates.start()
    try:
        if settings.app_apk_worker_enabled:
            _apk_uploads().start()
        if settings.app_apk_external_enabled:
            _apk_external().start()
        conversion_service.start()
        await restore_stream_sessions()
        yield
    finally:
        if _apk_external_service is not None:
            await asyncio.to_thread(_apk_external_service.close)
        if _apk_upload_service is not None:
            await asyncio.to_thread(_apk_upload_service.close)
        await model_updates.close()
        await asyncio.to_thread(conversion_service.close)
        await asyncio.to_thread(database.close)
        await alert_delivery.close()
        await asyncio.gather(*(stream.close() for stream in streams.values()), return_exceptions=True)
        streams.clear()


from .observability import RequestTelemetry

_apk_upload_service = None
_apk_external_service = None
_app_update_service = None
_apk_upload_lock = threading.Lock()


def _apk_uploads():
    global _apk_upload_service
    if not settings.app_apk_worker_enabled:
        raise UploadError("apk_upload_disabled", 503)
    with _apk_upload_lock:
        if _apk_upload_service is None:
            _apk_upload_service = configured_uploads(database, settings)
    return _apk_upload_service


def _apk_external():
    global _apk_external_service
    if not settings.app_apk_external_enabled:
        raise UploadError("external_apk_disabled", 503)
    with _apk_upload_lock:
        if _apk_external_service is None:
            _apk_external_service = configured_external(database, settings)
    return _apk_external_service

app = FastAPI(title="Server Video Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestTelemetry)
def _app_updates():
    global _app_update_service
    if not settings.app_updates_enabled:
        from .app_updates.service import UpdateError
        raise UpdateError("service_unavailable")
    with _apk_upload_lock:
        if _app_update_service is None:
            _app_update_service = configured_updates(database, settings)
    return _app_update_service


app.include_router(create_auth_router())
app.include_router(create_update_router(_app_updates))
app.include_router(create_external_router(_apk_external))
app.include_router(create_upload_router(_apk_uploads, max_bytes=settings.app_apk_max_bytes,
    receive_seconds=settings.app_apk_receive_seconds))
app.include_router(create_media_authorization_router())
app.include_router(create_project_management_router())
app.include_router(create_scene_router(lambda: project_scenes))
app.include_router(create_model_update_router(lambda: model_updates))
app.include_router(create_service_principal_router())
from .system_alert_knowledge import SystemKnowledgeStore
from .alert_advice_api import create_system_alert_knowledge_router
alert_advice_knowledge_store = AlertAdviceKnowledgeStore(database, system=SystemKnowledgeStore(database))
app.include_router(create_alert_advice_router(lambda: alert_advice_knowledge_store))
app.include_router(create_system_alert_knowledge_router(lambda: alert_advice_knowledge_store))
alert_advice_generation_store = AlertAdviceGenerationStore(database)
alert_advice_service = AlertAdviceService(
    MockKnowledgeRetriever(alert_advice_knowledge_store), MockAdviceGenerator()
)
app.include_router(create_alert_advice_generation_router(
    lambda: alert_advice_generation_store,
    lambda: alert_advice_service,
    lambda: alert_disposition_store,
))
app.include_router(create_conversion_router(
    conversion_service,
    model_catalog,
    calibration_catalog=calibration_catalog,
    max_calibration_upload_bytes=settings.calibration_max_upload_bytes,
))
mount_admin_frontend(
    app,
    mode=settings.admin_frontend_mode,
    build_dir=Path(__file__).resolve().parents[1] / "admin-web" / "dist",
    preview_dir=Path(__file__).resolve().parents[1] / "admin-web" / "dist-preview",
)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/admin/", status_code=307)


def _stream_key(project_id: str, stream_id: str) -> tuple[str, str]:
    return project_id, stream_id


def get_stream(stream_id: str, project_id: str = DEFAULT_PROJECT_ID) -> StreamSession:
    stream = streams.get(_stream_key(project_id, stream_id))
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return stream


def _storage_error(_exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "stream_config_unavailable", "message": "stream configuration storage is unavailable"},
    )


def _stream_configuration(
    stream: StreamSession,
    *,
    display_name: str | None = None,
    source_type: str | None = None,
    enabled: bool = True,
    scene_id: str | None = None,
    plan_id: str | None = None,
    scene_revision: int | None = None,
) -> StreamConfiguration:
    source = str(stream.source_url) if stream.source_url is not None else None
    return StreamConfiguration(
        project_id=stream.project_id,
        stream_id=stream.stream_id,
        display_name=display_name or stream.stream_id,
        source_type=source_type or infer_source_type(stream.source_url),
        source_url=source,
        model_id=stream.model_catalog_id,
        model_version=stream.model_version,
        scene_id=scene_id,
        plan_id=plan_id,
        scene_revision=scene_revision,
        yolo_enabled=stream.yolo_enabled,
        confidence=float(stream.detector.confidence),
        max_fps=float(stream.max_fps),
        overlay_enabled=stream.overlay_enabled,
        enabled=enabled,
    )


def _resolve_stream_plan(project_id: str, scene_id: str | None, plan_id: str | None,
                         scene_revision: int | None):
    if not scene_id or not plan_id or scene_revision is None:
        raise HTTPException(409, detail={"code": "scene_plan_required", "message": "stream requires an explicit scene and plan"})
    resolved = project_scenes.resolve_plan(project_id, scene_id, plan_id, ScenePlanResolution(
        planId=plan_id, expectedRevision=scene_revision, target="pc", inputType="video",
        clientContractVersion=2, supportedExecutionModes=["single"],
    ))
    if resolved["execution"] != "single" or len(resolved["members"]) != 1:
        raise HTTPException(409, detail={"code": "stream_plan_not_supported", "message": "video streams currently require a single-member plan"})
    member = resolved["members"][0]
    if member.get("target") != "pc":
        raise HTTPException(409, detail={"code": "scene_target_mismatch", "message": "video streams require a PC scene member"})
    return resolved


def _source_model_version(project_id: str, source_id: str) -> str | None:
    stream = streams.get((project_id, source_id))
    if stream is not None and stream.model_version:
        return stream.model_version
    config = stream_config_store.get(source_id, project_id)
    return config.model_version if config else None


def _runtime_profile(project_id: str, source_id: str, model_id: str):
    if not project_model_assignments.project_active(project_id):
        return None
    stream = streams.get((project_id, source_id))
    config = stream_config_store.get(source_id, project_id)
    if (stream is None or config is None or not config.enabled or not model_id or
            config.model_id != model_id or stream.model_catalog_id != model_id or
            not config.model_version or stream.model_version != config.model_version):
        return None
    try:
        resolved = _resolve_stream_plan(project_id, config.scene_id, config.plan_id, config.scene_revision)
    except HTTPException:
        return None
    member = resolved["members"][0]
    if member["modelId"] != model_id or member["version"] != config.model_version:
        return None
    version = member["version"]
    try:
        published = model_catalog.is_published_release(model_id, version)
    except (ValueError, OSError):
        return None
    if not published:
        return None
    return member["parameterSnapshot"]


def _bind_registered_model(stream: StreamSession, model_id: str, version: str,
                           parameter_snapshot: dict[str, Any]) -> dict[str, Any]:
    try:
        item, path = model_catalog.resolve_server_model(model_id, version)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "model_not_found", "message": "model not found"})
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "model_not_available", "message": str(exc)})
    profile = parameter_snapshot
    if not profile or (profile.get("modelId") != model_id or profile.get("modelVersion") != version
                       or profile.get("platform") != "server"):
        raise HTTPException(409, detail={"code": "model_assignment_required", "message": "approved parameters are unavailable"})
    return stream.bind_model(
        model_id=model_id,
        model_path=str(path),
        scenario=item.get("scenario"),
        labels=item.get("labels"),
        imgsz=item.get("inputSize"),
        version=version,
        detection=profile["detection"],
        enabled_labels=[rule["rawLabel"] for rule in profile["alertRules"] if rule["enabled"]],
    )


async def _session_from_configuration(configuration: StreamConfiguration) -> StreamSession:
    stream = StreamSession(
        configuration.stream_id,
        configuration.runtime_source(),
        project_id=configuration.project_id,
        alert_runtime=server_alert_runtime,
        model_authorizer=lambda: _runtime_profile(configuration.project_id, configuration.stream_id, stream.model_catalog_id) is not None,
    )
    stream.detector.confidence = configuration.confidence
    stream.overlay_enabled = configuration.overlay_enabled
    await stream.set_max_fps(configuration.max_fps)
    resolved = _resolve_stream_plan(configuration.project_id, configuration.scene_id,
                                    configuration.plan_id, configuration.scene_revision)
    member = resolved["members"][0]
    _bind_registered_model(stream, member["modelId"], member["version"], member["parameterSnapshot"])
    if (configuration.model_id, configuration.model_version) != (member["modelId"], member["version"]):
        raise HTTPException(409, detail={"code": "scene_plan_model_changed", "message": "selected scene plan no longer resolves to the configured model"})
    await stream.set_yolo(configuration.yolo_enabled)
    if configuration.enabled:
        await stream.start()
    return stream


async def restore_stream_sessions() -> None:
    """Restore enabled control-plane records without making one bad source fatal."""
    configurations = await asyncio.to_thread(stream_config_store.list_all)
    stream_restore_errors.clear()
    for configuration in configurations:
        key = _stream_key(configuration.project_id, configuration.stream_id)
        if not configuration.enabled or key in streams:
            continue
        try:
            streams[key] = await _session_from_configuration(configuration)
        except Exception:
            # Do not expose model paths, source credentials, or driver errors.
            stream_restore_errors[key] = "persisted stream could not be restored"


def public_alert_event(event):
    """Enrich an already authorized event; never persist display labels as identity."""
    from .model_display import catalog_model_name, model_display_name, UNNAMED_MODEL
    result = _public_alert_event(event)
    model = result.get("model")
    if isinstance(model, dict):
        name = catalog_model_name(model_catalog, model.get("modelId"), model.get("version", model.get("modelVersion")))
        model["name"] = name if name != UNNAMED_MODEL else model_display_name(model)
    return result


def _configured_model(model_id: str | None, version: str | None = None) -> dict[str, Any]:
    if not model_id:
        return {"modelId": None, "catalog_model_id": None, "name": "unbound"}
    try:
        item = model_catalog.get(model_id, version)
    except KeyError:
        return {"modelId": model_id, "catalog_model_id": model_id, "name": model_id, "available": False}
    return {
        "modelId": model_id,
        "modelVersion": item["version"],
        "catalog_model_id": model_id,
        "name": item.get("name") or model_id,
        "scenario": item.get("scenario"),
        "available": True,
    }


def _stream_payload(configuration: StreamConfiguration, stream: StreamSession | None) -> dict[str, Any]:
    if stream is None:
        runtime_state = "not_started" if configuration.enabled else "disabled"
        restore_error = stream_restore_errors.get(_stream_key(configuration.project_id, configuration.stream_id))
        if restore_error:
            runtime_state = "error"
        return {
            **configuration.public(),
            "state": runtime_state,
            "runtime_state": runtime_state,
            "runtime_available": False,
            "configuration_state": "enabled" if configuration.enabled else "disabled",
            "frames_received": 0,
            "frames_processed": 0,
            "frames_dropped": 0,
            "frames_fallback": 0,
            "received_fps": 0.0,
            "processed_fps": 0.0,
            "output_fps": 0.0,
            "last_latency_ms": None,
            "p95_latency_ms": None,
            "active_subscribers": 0,
            "detections_last": 0,
            "alert_error": None,
            "publish_state": "retired",
            "viewers": 0,
            "last_error": restore_error,
            "model": _configured_model(configuration.model_id, configuration.model_version),
        }
    return {
        "project_id": stream.project_id,
        "stream_id": stream.stream_id,
        "state": stream.state,
        "runtime_state": stream.state,
        "runtime_available": not stream.closed,
        "configuration_state": "enabled" if configuration.enabled else "disabled",
        "yolo_enabled": stream.yolo_enabled,
        **stream.metrics(),
        "last_error": stream.last_error,
        "confidence": stream.detector.confidence,
        "max_fps": stream.max_fps,
        "overlay_enabled": stream.overlay_enabled,
        "model": stream.model_metadata(),
        **configuration.public(),
    }


@app.get("/healthz")
async def healthz():
    database_state = await asyncio.to_thread(database.health)
    payload = {
        "status": "ok" if database_state["status"] in {"ok", "fallback"} else "degraded",
        "streams": len(streams),
        "database": database_state,
    }
    if database_state["status"] == "unavailable":
        return JSONResponse(payload, status_code=503)
    return payload


def _stream_totals(values):
    snapshots = [stream.metrics() for stream in values]
    return {"total": len(snapshots),
            "framesReceived": sum(int(s.get("frames_received", 0)) for s in snapshots),
            "framesProcessed": sum(int(s.get("frames_processed", 0)) for s in snapshots),
            "framesDropped": sum(int(s.get("frames_dropped", 0)) for s in snapshots)}


@app.get("/aiyoloapi/metrics")
async def metrics(_ = Depends(require_platform_capability(PLATFORM_OBSERVABILITY_READ))):
    return {
        "system": system_metrics(),
        "scope": "platform",
        "streams": _stream_totals(streams.values()),
        "modelUpdates": await asyncio.to_thread(model_updates.metrics),
    }


@app.get("/aiyoloapi/projects/{project_id}/dashboard/stats")
@app.get("/aiyoloapi/dashboard/stats", include_in_schema=False)
async def dashboard_statistics(
    range: Literal["today", "7d", "30d"] = Query(default="today"),
    context: ProjectContext = Depends(require_project_capability(PROJECT_READ)),
    project_id: str | None = None,
):
    """Return persisted dashboard statistics plus current stream telemetry."""
    try:
        return await asyncio.to_thread(dashboard_stats.build, range, streams, {}, context.project_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "dashboard_stats_unavailable", "message": "dashboard statistics are unavailable"},
        ) from exc


def _catalog_scope(request: Request):
    principal = authenticate(request)
    if principal is None or principal.legacy:
        raise authentication_error("catalog session")
    requested_project = request.path_params.get("project_id") or request.headers.get("x-project-id")
    if not requested_project:
        if principal.is_admin:
            return None
        requested_project = _project_id(request)
    context = resolve_project_context(principal, requested_project)
    request.state.project_id = context.project_id
    if PROJECT_READ not in context.capabilities:
        raise HTTPException(403, detail={"code": "capability_required", "message": "project read required"})
    if context.platform_entry:
        _audit_platform_entry(context, request, "HTTP")
    return context


def _project_catalog_models(context, target=None):
    results = []
    for assignment in project_model_assignments.list(context.project_id):
        if target is not None and assignment["target"] != target:
            continue
        if not assignment["enabled"] and PROJECT_MODELS_ASSIGN not in context.capabilities:
            continue
        try:
            model = model_catalog.get(assignment["modelId"], assignment["modelVersion"])
        except KeyError:
            continue
        # A project projection must not expose versions of an unrelated release.
        model["availableVersions"] = [assignment["modelVersion"]]
        model["latestVersion"] = assignment["modelVersion"]
        model["isLatest"] = True
        model["assignment"] = assignment
        model["active"] = assignment["enabled"]
        assignment_target = "pc" if assignment["parameterPlatform"] == "server" else "mobile"
        target_usable = project_target_usable(model, assignment_target)
        if not target_usable and PROJECT_MODELS_ASSIGN not in context.capabilities:
            continue
        model["serverBindable"] = bool(assignment["enabled"] and target_usable and model["serverReady"]
                                       and assignment["parameterPlatform"] == "server")
        model["effectiveParameters"] = project_model_assignments.snapshot(
            context.project_id, assignment["modelId"], assignment["modelVersion"], assignment["parameterPlatform"])
        model["artifacts"] = [artifact for artifact in model["artifacts"]
                              if artifact["platform"] == assignment["parameterPlatform"]
                              and target_usable and assignment["enabled"]]
        for artifact in model["artifacts"]:
            url = (f"/aiyoloapi/projects/{quote(context.project_id, safe='')}/models/"
                   f"{quote(model['modelId'], safe='')}/versions/{quote(model['version'], safe='')}/"
                   f"artifacts/{quote(artifact['artifactId'], safe='')}/download")
            artifact["url"] = artifact["versionedUrl"] = url
        if model["artifacts"]:
            model["downloadUrl"] = model["artifacts"][0]["url"]
            for field in ("format", "sizeBytes", "sha256"):
                model[field] = model["artifacts"][0][field]
        else:
            model.pop("downloadUrl", None)
        results.append(model)
    # One logical release can have two independent approved deployments. Keep
    # one catalog row per release for existing clients; never merge versions.
    grouped = {}
    for model in results:
        key = (model["modelId"], model["version"])
        assignment = model["assignment"]
        target_key = "pc" if assignment["parameterPlatform"] == "server" else "mobile"
        if key not in grouped:
            grouped[key] = model
            model["assignments"] = [assignment]
            model["effectiveParametersByTarget"] = {target_key: model["effectiveParameters"]}
            continue
        existing = grouped[key]
        existing["assignments"].append(assignment)
        existing["effectiveParametersByTarget"][target_key] = model["effectiveParameters"]
        existing["artifacts"].extend(model["artifacts"])
        existing["serverBindable"] = existing["serverBindable"] or model["serverBindable"]
        existing["active"] = existing["active"] or model["active"]
        # Old Android clients expect a single approved Android snapshot.
        if assignment["parameterPlatform"] == "android" and assignment["enabled"]:
            existing["assignment"] = assignment
            existing["effectiveParameters"] = model["effectiveParameters"]
    for model in grouped.values():
        preferred_assignment = next((a for a in model["assignments"]
            if a["enabled"] and a["parameterPlatform"] == "android"), None)
        preferred_assignment = preferred_assignment or next((a for a in model["assignments"] if a["enabled"]), model["assignment"])
        model["assignment"] = preferred_assignment
        preferred_target = "pc" if preferred_assignment["parameterPlatform"] == "server" else "mobile"
        model["effectiveParameters"] = model["effectiveParametersByTarget"][preferred_target]
        if model["artifacts"]:
            preferred = next((a for a in model["artifacts"]
                if a["platform"] == model["assignment"]["parameterPlatform"]), model["artifacts"][0])
            model["downloadUrl"] = preferred["url"]
            for field in ("format", "sizeBytes", "sha256"):
                model[field] = preferred[field]
    return list(grouped.values())


def _project_catalog_release(context, model_id, version=None, target=None):
    candidates = [item for item in _project_catalog_models(context, target=target)
                  if item["modelId"] == model_id and (version is None or item["version"] == version)]
    if not candidates:
        raise HTTPException(404, detail={"code": "model_not_found", "message": "model not assigned to project"})
    if version is None and len({item["version"] for item in candidates}) != 1:
        raise HTTPException(409, detail={"code": "version_required", "message": "specify the assigned version"})
    return candidates[0]


@app.get("/aiyoloapi/projects/{project_id}/model-assignments")
async def list_project_assignments(project_id: str, target: Literal["pc", "mobile"] | None = None,
                                  context: ProjectContext = Depends(require_project_capability(PROJECT_READ))):
    rows = project_model_assignments.list(context.project_id, target)
    if PROJECT_MODELS_ASSIGN not in context.capabilities:
        rows = [row for row in rows if row["enabled"]]
    return {"projectId": context.project_id, "assignments": rows}


@app.get("/aiyoloapi/projects/{project_id}/model-assignments/{project_model_id}")
async def get_project_assignment(project_id: str, project_model_id: str,
                                 context: ProjectContext = Depends(require_project_capability(PROJECT_READ))):
    row = project_model_assignments.get(context.project_id, project_model_id)
    if row is None or not row["enabled"] and PROJECT_MODELS_ASSIGN not in context.capabilities:
        raise HTTPException(404, detail={"code": "project_model_not_found", "message": "project model not found"})
    return row


@app.put("/aiyoloapi/projects/{project_id}/model-assignments")
async def set_project_assignment(project_id: str, body: ProjectModelAssignmentRequest,
                                 request: Request, context: ProjectContext = Depends(require_project_capability(PROJECT_MODELS_ASSIGN))):
    try:
        return project_model_assignments.save(context.project_id, body.modelId, body.modelVersion,
            body.target, body.parameterRevision, body.enabled, body.expectedRevision,
            context=context, request_id=request.headers.get("x-request-id", "")[:128] or None)
    except AssignmentConflict as exc:
        raise HTTPException(409, detail={"code": "assignment_conflict", "message": str(exc)}) from exc
    except ModelParameterError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": str(exc)}) from exc


@app.delete("/aiyoloapi/projects/{project_id}/model-assignments/{project_model_id}")
async def remove_project_assignment(project_id: str, project_model_id: str, expectedRevision: int,
                                    request: Request,
                                    context: ProjectContext = Depends(require_project_capability(PROJECT_MODELS_ASSIGN))):
    try:
        return project_model_assignments.remove(context.project_id, project_model_id, expectedRevision,
            context=context, request_id=request.headers.get("x-request-id", "")[:128] or None)
    except AssignmentConflict as exc:
        raise HTTPException(409, detail={"code": "assignment_conflict", "message": str(exc)}) from exc


@app.get("/aiyoloapi/projects/{project_id}/models/available")
async def available_project_models(project_id: str,
                                   context: ProjectContext = Depends(require_project_capability(PROJECT_MODELS_ASSIGN))):
    # Owner-only selection preview; this does not grant artifact downloads.
    results = []
    for row in model_catalog.list_models():
        if not (row["status"] == "PUBLISHED" and row["releaseEligible"]):
            continue
        platforms = [
            platform for platform, target in (("server", "pc"), ("android", "mobile"))
            if project_target_usable(row, target)
        ]
        if not platforms:
            continue
        projection = {key: row.get(key) for key in (
            "modelId", "name", "version", "scenario", "status", "releaseEligible",
            "serverReady", "androidReady", "supportedTargets", "targetReadiness", "targetReleaseEligible", "labels",
        )}
        projection["parameterProfiles"] = {
            platform: model_parameter_store.get(row, platform, context.project_id)
            for platform in platforms
        }
        results.append(projection)
    return {"models": results}


@app.get("/aiyoloapi/projects/{project_id}/models")
async def project_models(project_id: str, target: Literal["pc", "mobile"] | None = None,
                         context: ProjectContext = Depends(require_project_capability(PROJECT_READ))):
    return {"models": _project_catalog_models(context, target)}


@app.get("/aiyoloapi/projects/{project_id}/models/{model_id}")
async def project_model_detail(project_id: str, model_id: str,
                               target: Literal["pc", "mobile"] | None = None,
                               context: ProjectContext = Depends(require_project_capability(PROJECT_READ))):
    return _project_catalog_release(context, model_id, target=target)


@app.get("/aiyoloapi/projects/{project_id}/models/{model_id}/versions/{version}")
async def project_model_release(project_id: str, model_id: str, version: str,
                                target: Literal["pc", "mobile"] | None = None,
                                context: ProjectContext = Depends(require_project_capability(PROJECT_READ))):
    return _project_catalog_release(context, model_id, version, target)


@app.get("/aiyoloapi/models")
async def list_models(
    request: Request,
    scenario: str | None = Query(default=None, min_length=1, max_length=128),
):
    context = _catalog_scope(request)
    models = model_catalog.list_models() if context is None else _project_catalog_models(context)
    if scenario is not None:
        models = [model for model in models if model.get("scenario") == scenario]
    return {"models": models}


@app.get("/aiyoloapi/models/{model_id}")
async def model_detail(model_id: str, request: Request):
    context = _catalog_scope(request)
    if context is not None:
        return _project_catalog_release(context, model_id)
    try:
        model = model_catalog.get(model_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_not_found", "message": "model not found"},
        )
    return model


@app.get("/aiyoloapi/projects/{project_id}/metrics")
async def project_metrics(project_id: str, context: ProjectContext = Depends(require_project_capability(PROJECT_READ))):
    snapshots = [stream.metrics() for (pid, _), stream in streams.items() if pid == context.project_id]
    # Fixed field names; project identity is response context, never a metrics label.
    return {"projectId": context.project_id, "streams": {
        "total": len(snapshots),
        "framesReceived": sum(int(item.get("frames_received", 0)) for item in snapshots),
        "framesProcessed": sum(int(item.get("frames_processed", 0)) for item in snapshots),
        "framesDropped": sum(int(item.get("frames_dropped", 0)) for item in snapshots),
    }}


@app.get("/aiyoloapi/models/{model_id}/versions")
async def model_versions(model_id: str, request: Request):
    context = _catalog_scope(request)
    if context is not None:
        matches = [item for item in _project_catalog_models(context) if item["modelId"] == model_id]
        if not matches:
            raise HTTPException(404, detail={"code": "model_not_found", "message": "model not assigned to project"})
        return {"modelId": model_id, "versions": matches}
    try:
        return {"modelId": model_id, "versions": model_catalog.versions(model_id)}
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_not_found", "message": "model not found"},
        )


@app.get("/aiyoloapi/models/{model_id}/versions/{version}")
async def model_version_detail(model_id: str, version: str, request: Request):
    context = _catalog_scope(request)
    if context is not None:
        return _project_catalog_release(context, model_id, version)
    try:
        return model_catalog.get(model_id, version)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_not_found", "message": "model release not found"},
        )


@app.post("/aiyoloapi/models/{model_id}/migrate")
async def migrate_model_release(
    model_id: str,
    request: ModelMigrationRequest,
    raw_request: Request,
    _: None = Depends(require_admin),
):
    """Move one explicitly named historical release to a stable model family."""
    bound_streams = await _bound_model_streams(model_id)
    if bound_streams or project_model_assignments.references(model_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "model_in_use",
                "message": "source model family is bound to one or more video streams",
                "streamIds": bound_streams,
            },
        )
    actor = raw_request.headers.get("x-operator-id") or raw_request.headers.get("x-actor") or "admin"
    try:
        return model_catalog.migrate_release(
            model_id,
            request.targetModelId,
            request.version,
            request.reason,
            actor,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_release_not_found", "message": "source model release not found"},
        ) from exc
    except ValueError as exc:
        message = str(exc)
        code = "migration_conflict" if "already exists" in message else "invalid_migration"
        raise HTTPException(status_code=409, detail={"code": code, "message": message}) from exc


async def _bound_model_streams(model_id: str) -> list[str]:
    runtime_bindings = {
        f"{project_id}/{stream_id}"
        for (project_id, stream_id), stream in streams.items()
        if stream.model_catalog_id == model_id
    }
    try:
        persisted_bindings = {
            f"{item.project_id}/{item.stream_id}"
            for item in await asyncio.to_thread(stream_config_store.list_all)
            if item.model_id == model_id
        }
    except Exception as exc:
        raise _storage_error(exc) from exc
    return sorted(runtime_bindings | persisted_bindings)


@app.delete("/aiyoloapi/models/{model_id}/versions/{version}")
async def uninstall_model_version(model_id: str, version: str, request: Request,
    principal=Depends(require_platform_capability(PLATFORM_MODELS_MANAGE))):
    expected, key = deletion_headers(request)
    return await _lifecycle_call(_model_removal().execute, model_id, version, expected, key, principal,
                                   getattr(request.state, "request_id", None))


def _model_removal():
    return ModelRemoval(auth.database, model_catalog, project_model_assignments, project_scenes, stream_config_store, streams)


async def _lifecycle_call(operation, *args):
    try:
        return await asyncio.to_thread(operation, *args)
    except HTTPException:
        raise
    except (OSError, RuntimeError, SQLAlchemyError):
        raise HTTPException(503, detail={"code": "resource_lifecycle_unavailable",
            "message": "operation could not be confirmed; retain the same idempotency key and verify before retry"})
    except ValueError:
        raise HTTPException(409, detail={"code": "resource_lifecycle_conflict",
            "message": "resource changed or has a pending lifecycle operation; refresh impact"})


@app.get("/aiyoloapi/models/{model_id}/versions/{version}/removal-impact")
async def model_version_removal_impact(model_id: str, version: str,
    principal=Depends(require_platform_capability(PLATFORM_MODELS_MANAGE))):
    return await _lifecycle_call(_model_removal().impact, model_id, version, principal)


@app.get("/aiyoloapi/models/{model_id}/removal-impact")
async def model_removal_impact(model_id: str,
    principal=Depends(require_platform_capability(PLATFORM_MODELS_MANAGE))):
    return await _lifecycle_call(_model_removal().impact, model_id, None, principal)


@app.post("/aiyoloapi/models/{model_id}/versions/{version}/publish")
async def publish_model_version(
    model_id: str, version: str, body: ModelPublishRequest,
    request: Request,
    principal=Depends(require_platform_capability(PLATFORM_MODELS_MANAGE)),
):
    try:
        before = model_catalog.get(model_id, version)
        result = model_catalog.publish_release(model_id, version, body.targets,
            license_approved=body.licenseApproved, reason=body.reason, actor=principal.account_id,
            signer=ModelManifestSigner(settings.model_signing_key_id, settings.model_signing_private_key_path,
                settings.model_signing_trusted_key_ids, settings.model_signing_revoked_key_ids))
        model_updates.wake()  # Registry remains truth if DB projection is temporarily unavailable.
        def record_audit(session):
            audit_change(session, principal, getattr(request.state, "request_id", None),
                "model.publish", "model_release", f"{model_id}@{version}",
                {"status": before["status"], "targetReleaseEligible": before["targetReleaseEligible"]},
                {"status": result["status"], "targetReleaseEligible": result["targetReleaseEligible"],
                 "reason": body.reason, "licenseApproved": True})
        if auth.database.enabled:
            with auth.database.session() as session:
                record_audit(session)
        else:
            record_audit(None)
        return result
    except KeyError:
        raise HTTPException(404, detail={"code": "model_not_found", "message": "model release not found"})
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "model_publish_rejected", "message": str(exc)})


@app.post("/aiyoloapi/models/{model_id}/versions/{version}/validate-pc-runtime")
async def validate_pc_model_runtime(
    model_id: str, version: str,
    principal=Depends(require_platform_capability(PLATFORM_MODELS_MANAGE)),
):
    del principal
    validation_dir = conversion_service.root / "runtime-validation" / uuid.uuid4().hex
    try:
        item = model_catalog.get(model_id, version)
        if "pc" not in item["supportedTargets"]:
            raise HTTPException(409, detail={"code": "model_target_not_supported", "message": "model release does not support pc"})
        if item.get("format") != "pt":
            raise HTTPException(409, detail={"code": "pc_runtime_validation_unsupported", "message": "当前运行时验证仅支持 PT 模型"})
        entry = model_catalog._find_entry(model_catalog._load(), model_id, version)
        source = model_catalog._artifact_path(entry)
        if not item.get("exists") or not item.get("hashValid"):
            raise HTTPException(409, detail={"code": "model_artifact_invalid", "message": "模型文件缺失或完整性校验失败"})
        validation_dir.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(source, validation_dir / "source.pt")
        config = conversion_service.config().model_copy(update={"mode": "local", "python_path": sys.executable})
        result = await asyncio.to_thread(
            conversion_service.runner.run_worker, config, "inspect", validation_dir, threading.Event(),
        )
        return await asyncio.to_thread(model_catalog.record_pc_runtime_validation, model_id, version, result)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "model_not_found", "message": "model release not found"}) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(409, detail={"code": "pc_runtime_validation_failed", "message": str(exc)[:500]}) from exc
    finally:
        await asyncio.to_thread(shutil.rmtree, validation_dir, True)


@app.post("/aiyoloapi/models/{model_id}/versions/{version}/deprecate")
async def deprecate_model_version(
    model_id: str,
    version: str,
    raw_request: Request,
    request: ModelLifecycleRequest | None = None,
    principal=Depends(require_platform_capability(PLATFORM_MODELS_MANAGE)),
):
    expected, key = deletion_headers(raw_request, allow_body=True)
    return await _lifecycle_call(_model_removal().execute, model_id, version, expected, key, principal,
        getattr(raw_request.state, "request_id", None), "DEPRECATED", request.reason if request else None)


@app.post("/aiyoloapi/models/{model_id}/versions/{version}/revoke")
async def revoke_model_version(
    model_id: str,
    version: str,
    raw_request: Request,
    request: ModelLifecycleRequest | None = None,
    principal=Depends(require_platform_capability(PLATFORM_MODELS_MANAGE)),
):
    expected, key = deletion_headers(raw_request, allow_body=True)
    return await _lifecycle_call(_model_removal().execute, model_id, version, expected, key, principal,
        getattr(raw_request.state, "request_id", None), "REVOKED", request.reason if request else None)


@app.delete("/aiyoloapi/models/{model_id}")
async def uninstall_model(model_id: str, request: Request,
    principal=Depends(require_platform_capability(PLATFORM_MODELS_MANAGE))):
    expected, key = deletion_headers(request)
    return await _lifecycle_call(_model_removal().execute, model_id, None, expected, key, principal,
                                   getattr(request.state, "request_id", None))


def _parameter_model(model_id: str, version: str | None = None) -> dict:
    try:
        return model_catalog.get(model_id, version)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_not_found", "message": "model not found"},
        )


@app.get("/aiyoloapi/platform/models/{model_id}/parameters")
@app.get("/aiyoloapi/models/{model_id}/parameters", include_in_schema=False)
async def get_model_parameters(
    model_id: str,
    platform: Literal["android", "server"] = Query(default="android"),
    version: str | None = None,
    _ = Depends(require_platform_capability(PLATFORM_MODELS_MANAGE)),
):
    try:
        return model_parameter_store.get(_parameter_model(model_id, version), platform)
    except ModelParameterError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)})


@app.put("/aiyoloapi/platform/models/{model_id}/parameters")
@app.put("/aiyoloapi/models/{model_id}/parameters", include_in_schema=False)
async def update_model_parameters(
    model_id: str,
    request: ModelParameterRequest,
    http_request: Request,
    platform: Literal["android", "server"] = Query(default="android"),
    version: str | None = None,
    principal = Depends(require_platform_capability(PLATFORM_MODELS_MANAGE)),
):
    model = _parameter_model(model_id, version)
    values = request.model_dump(exclude={"expectedRevision"}, exclude_none=True)
    try:
        return model_parameter_store.save(
            model,
            platform,
            values,
            principal.account_id,
            _expected_revision(request.expectedRevision),
            context=principal,
            request_id=http_request.headers.get("x-request-id", "")[:128] or None,
        )
    except ModelParameterConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    except ModelParameterError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


@app.delete("/aiyoloapi/platform/models/{model_id}/parameters")
@app.delete("/aiyoloapi/models/{model_id}/parameters", include_in_schema=False)
async def reset_model_parameters(
    model_id: str,
    http_request: Request,
    expectedRevision: int = Query(ge=0),
    platform: Literal["android", "server"] = Query(default="android"),
    version: str | None = None,
    principal = Depends(require_platform_capability(PLATFORM_MODELS_MANAGE)),
):
    try:
        return model_parameter_store.reset(
            _parameter_model(model_id, version),
            platform,
            principal.account_id,
            expected_revision=expectedRevision,
            context=principal,
            request_id=http_request.headers.get("x-request-id", "")[:128] or None,
        )
    except ModelParameterConflict as exc:
        raise HTTPException(409, detail={"code": exc.code, "message": str(exc)})
    except ModelParameterError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)})


def _project_parameter_model(model_id, context, version=None):
    assignments = project_model_assignments.assigned(context.project_id, model_id)
    versions = {item["modelVersion"] for item in assignments}
    if not versions or version is not None and version not in versions:
        raise HTTPException(404, detail={"code": "model_not_found", "message": "model not found"})
    if version is None and len(versions) > 1:
        raise HTTPException(409, detail={"code": "version_required", "message": "specify an assigned model version"})
    try:
        return model_catalog.get(model_id, version or next(iter(versions)))
    except KeyError:
        raise HTTPException(404, detail={"code": "model_not_found", "message": "model not found"})


def _scene_profile_model(project_id, scene_id, member_id, scene_revision):
    # The scene member owns its override; the project inventory remains unchanged.
    scene = project_scenes.visible(project_id, scene_id, manage=True)
    if scene["revision"] != scene_revision:
        raise HTTPException(409, detail={"code": "revision_conflict", "message": "scene revision was changed"})
    member = next((item for item in scene["models"] if item["memberId"] == member_id), None)
    if member is None:
        raise HTTPException(404, detail={"code": "scene_member_not_found", "message": "scene member not found"})
    project_scenes.validate_models([member], scene["inputTypes"])
    return project_scenes.catalog_model(member), "android" if member["target"] == "mobile" else "server"


@app.get("/aiyoloapi/projects/{project_id}/scenes/{scene_id}/members/{member_id}/parameter-profile")
async def get_scene_member_profile(project_id: str, scene_id: str, member_id: str,
    scene_revision: int = Query(ge=1, alias="sceneRevision"),
    context: ProjectContext = Depends(require_project_capability(PROJECT_SCENES_MANAGE))):
    model, platform = _scene_profile_model(project_id, scene_id, member_id, scene_revision)
    return project_scenes.member_profile(project_id, scene_id, member_id, scene_revision)


@app.put("/aiyoloapi/projects/{project_id}/scenes/{scene_id}/members/{member_id}/parameter-profile")
async def update_scene_member_profile(project_id: str, scene_id: str, member_id: str,
    request: ModelParameterRequest, http_request: Request,
    scene_revision: int = Query(ge=1, alias="sceneRevision"),
    context: ProjectContext = Depends(require_project_capability(PROJECT_SCENES_MANAGE)),
    _parameter_authority=Depends(require_project_capability(PROJECT_MODELS_ASSIGN))):
    try:
        # Match scene approval's scene-before-parameters lock order. Revalidate
        # authority and the binding again inside the parameter transaction.
        with project_scenes._lock:
            model, platform = _scene_profile_model(project_id, scene_id, member_id, scene_revision)
            return project_scenes.save_member_profile(project_id, scene_id, member_id, scene_revision,
                request.model_dump(exclude={"expectedRevision"}, exclude_none=True),
                expected_revision=_expected_revision(request.expectedRevision),
                actor=context.principal.account_id, context=context,
                request_id=http_request.headers.get("x-request-id", "")[:128] or None)
    except ModelParameterConflict as exc:
        raise HTTPException(409, detail={"code": exc.code, "message": str(exc)})
    except ModelParameterError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": str(exc)})


@app.get("/aiyoloapi/projects/{project_id}/models/{model_id}/parameters")
async def get_project_model_parameters(project_id: str, model_id: str,
    platform: Literal["android", "server"] = Query(default="android"), version: str | None = None,
    context: ProjectContext = Depends(require_project_capability(PROJECT_READ))):
    try:
        model = _project_parameter_model(model_id, context, version)
        if PROJECT_MODELS_ASSIGN not in context.capabilities:
            snapshot = project_model_assignments.snapshot(context.project_id, model_id, model["version"], platform)
            if snapshot is None or not (model["status"] == "PUBLISHED" and model["releaseEligible"]):
                raise HTTPException(404, detail={"code": "model_not_found", "message": "approved model parameters not found"})
            return {**snapshot, "source": "approved", "projectId": context.project_id}
        return model_parameter_store.get(model, platform, context.project_id)
    except ModelParameterError as exc:
        raise HTTPException(503, detail={"code": exc.code, "message": str(exc)})


@app.put("/aiyoloapi/projects/{project_id}/models/{model_id}/parameters")
async def update_project_model_parameters(project_id: str, model_id: str, request: ModelParameterRequest,
    http_request: Request, platform: Literal["android", "server"] = Query(default="android"),
    version: str | None = None, context: ProjectContext = Depends(require_project_capability(PROJECT_MODELS_ASSIGN))):
    try:
        identity = _mutation_identity(context, http_request)
        return model_parameter_store.save(_project_parameter_model(model_id, context, version), platform,
            request.model_dump(exclude={"expectedRevision"}, exclude_none=True),
            expected_revision=_expected_revision(request.expectedRevision), **identity)
    except ModelParameterConflict as exc:
        raise HTTPException(409, detail={"code": exc.code, "message": str(exc)})
    except ModelParameterError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": str(exc)})


@app.delete("/aiyoloapi/projects/{project_id}/models/{model_id}/parameters")
async def reset_project_model_parameters(project_id: str, model_id: str, http_request: Request,
    expectedRevision: int = Query(ge=0), platform: Literal["android", "server"] = Query(default="android"),
    version: str | None = None, context: ProjectContext = Depends(require_project_capability(PROJECT_MODELS_ASSIGN))):
    try:
        return model_parameter_store.reset(_project_parameter_model(model_id, context, version), platform,
            expected_revision=expectedRevision, **_mutation_identity(context, http_request))
    except ModelParameterConflict as exc:
        raise HTTPException(409, detail={"code": exc.code, "message": str(exc)})
    except ModelParameterError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": str(exc)})


def _model_download_release(request: Request, model_id: str, version: str | None, artifact_id: str):
    context = _catalog_scope(request)
    if context is None:
        return version
    if context.lifecycle_state != PROJECT_ACTIVE:
        raise HTTPException(403, detail={"code": "project_inactive", "message": "project downloads are disabled"})
    approved = _project_catalog_release(context, model_id, version)
    release = model_catalog.get(model_id, approved["version"])
    selected_artifact = next((a for a in release["artifacts"] if a["artifactId"] == artifact_id), None)
    if selected_artifact is None or selected_artifact["platform"] not in {"server", "android"}:
        raise HTTPException(404, detail={"code": "model_not_found", "message": "artifact not assigned"})
    target = "pc" if selected_artifact["platform"] == "server" else "mobile"
    model = _project_catalog_release(context, model_id, approved["version"], target)
    if (not model["assignment"]["enabled"] or
            not (model["status"] == "PUBLISHED" and model["releaseEligible"])
            or not model["effectiveParameters"]):
        raise HTTPException(404, detail={"code": "model_not_found", "message": "model is not available"})
    artifact = next((item for item in model["artifacts"] if item["artifactId"] == artifact_id), None)
    if artifact is None:
        raise HTTPException(404, detail={"code": "model_not_found", "message": "artifact not assigned"})
    if (artifact["platform"] == "android" and not model["androidReady"] or
            artifact["platform"] == "server" and not model["serverReady"] or
            artifact["platform"] not in {"android", "server"}):
        raise HTTPException(409, detail={"code": "model_not_available", "message": "artifact is unavailable"})
    target = "pc" if artifact["platform"] == "server" else "mobile"
    if not project_target_usable(model, target):
        raise HTTPException(409, detail={"code": "model_target_not_published", "message": "artifact target is not approved"})
    return model["version"]


@app.get("/aiyoloapi/projects/{project_id}/models/{model_id}/artifacts/{artifact_id}/download")
@app.get("/aiyoloapi/models/{model_id}/artifacts/{artifact_id}/download")
async def download_model_artifact(
    model_id: str,
    artifact_id: str,
    request: Request,
    project_id: str | None = None,
):
    """Stream a catalog artifact after an on-disk size/hash revalidation.

    The token is accepted only by the header dependency above.  File paths stay
    server-side; clients receive safe download metadata and the advertised
    SHA-256 in ``X-Model-SHA256`` for an independent post-download check.
    """
    try:
        version = _model_download_release(request, model_id, None, artifact_id)
        artifact, path = model_catalog.get_artifact(model_id, artifact_id, version)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "model_not_found", "message": "model or artifact not found", "retryable": False}},
        )
    except (OSError, ValueError):
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "model_not_available", "message": "artifact is unavailable or failed integrity check", "retryable": True}},
        )

    from .model_updates.download import artifact_response
    return artifact_response(request, artifact, path, acquire=_acquire_model_download,
        release=_release_model_download, chunk_size=int(settings.model_download_chunk_size))


@app.get("/aiyoloapi/projects/{project_id}/models/{model_id}/versions/{version}/artifacts/{artifact_id}/download")
@app.get("/aiyoloapi/models/{model_id}/versions/{version}/artifacts/{artifact_id}/download")
async def download_model_version_artifact(
    model_id: str,
    version: str,
    artifact_id: str,
    request: Request,
    project_id: str | None = None,
):
    """Download an immutable versioned artifact using the same integrity guardrails."""
    try:
        approved_version = _model_download_release(request, model_id, version, artifact_id)
        artifact, path = model_catalog.get_artifact(model_id, artifact_id, approved_version)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "model_not_found", "message": "model release or artifact not found", "retryable": False}},
        )
    except (OSError, ValueError):
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "model_not_available", "message": "artifact is unavailable or failed integrity check", "retryable": True}},
        )

    from .model_updates.download import artifact_response
    return artifact_response(request, artifact, path, acquire=_acquire_model_download,
        release=_release_model_download, chunk_size=int(settings.model_download_chunk_size))


@app.post("/aiyoloapi/models/{model_id}/activate")
async def activate_model(model_id: str, _: None = Depends(require_admin)):
    try:
        model = model_catalog.activate(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"active_model": model}


@app.post("/aiyoloapi/models/register")
async def register_models(request: RegisterManifestRequest, _: None = Depends(require_admin)):
    try:
        models = model_catalog.register_manifest(request.manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"models": models}


# --- Runtime alert rule management (M11-T07) -------------------------------
def _expected_revision(value: int | None) -> int:
    if value is None:
        raise HTTPException(status_code=422, detail={"code": "expected_revision_required", "message": "expectedRevision is required"})
    return value


def _rule_error(exc):
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})
    return HTTPException(status_code=409 if isinstance(exc, RuleConflict) else 422,
                         detail={"code": exc.code, "message": str(exc)})


def _mutation_identity(context, request):
    return {"project_id": context.project_id, "actor": context.principal.account_id,
            "context": context, "request_id": request.headers.get("x-request-id", "")[:128] or None}


@app.get("/aiyoloapi/projects/{project_id}/rules")
@app.get("/aiyoloapi/rules", include_in_schema=False)
async def list_rules(context: ProjectContext = Depends(require_project_capability(PROJECT_READ)), project_id: str | None = None):
    return {"projectId": context.project_id, "rules": rule_registry.list(context.project_id)}


@app.get("/aiyoloapi/projects/{project_id}/rules/audit")
@app.get("/aiyoloapi/rules/audit", include_in_schema=False)
async def list_rule_audit(rule_id: str | None = Query(default=None), context: ProjectContext = Depends(require_project_capability(PROJECT_AUDIT_READ)), project_id: str | None = None):
    return {"projectId": context.project_id, "audit": rule_registry.audits(rule_id, context.project_id)}


@app.get("/aiyoloapi/projects/{project_id}/rules/{rule_id}")
@app.get("/aiyoloapi/rules/{rule_id}", include_in_schema=False)
async def get_rule(rule_id: str, context: ProjectContext = Depends(require_project_capability(PROJECT_READ)), project_id: str | None = None):
    try:
        return rule_registry.get(rule_id, context.project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})


@app.post("/aiyoloapi/projects/{project_id}/rules", status_code=201)
@app.post("/aiyoloapi/rules", status_code=201, include_in_schema=False)
async def create_rule(request: RuleRequest, http_request: Request, context: ProjectContext = Depends(require_project_capability(PROJECT_RULES_MANAGE)), project_id: str | None = None):
    try:
        try:
            rule_registry.get(request.ruleId, context.project_id)
            raise HTTPException(status_code=409, detail={"code": "rule_already_exists", "message": "rule already exists"})
        except KeyError:
            pass
        return rule_registry.upsert(request.model_dump(exclude={"expectedRevision"}, exclude_none=True), expected_revision=0, **_mutation_identity(context, http_request))
    except RuleValidationError as exc:
        raise _rule_error(exc)


@app.put("/aiyoloapi/projects/{project_id}/rules/{rule_id}")
@app.put("/aiyoloapi/rules/{rule_id}", include_in_schema=False)
async def update_rule(rule_id: str, request: RuleRequest, http_request: Request, context: ProjectContext = Depends(require_project_capability(PROJECT_RULES_MANAGE)), project_id: str | None = None):
    if request.ruleId != rule_id:
        raise HTTPException(status_code=400, detail={"code": "RULE_ID_MISMATCH", "message": "ruleId does not match path"})
    try:
        rule_registry.get(rule_id, context.project_id)
        return rule_registry.upsert(request.model_dump(exclude={"expectedRevision"}, exclude_none=True), expected_revision=_expected_revision(request.expectedRevision), **_mutation_identity(context, http_request))
    except (KeyError, RuleValidationError) as exc:
        raise _rule_error(exc)


@app.patch("/aiyoloapi/projects/{project_id}/rules/{rule_id}")
@app.patch("/aiyoloapi/rules/{rule_id}", include_in_schema=False)
async def patch_rule(rule_id: str, request: RulePatchRequest, http_request: Request, context: ProjectContext = Depends(require_project_capability(PROJECT_RULES_MANAGE)), project_id: str | None = None):
    try:
        current = rule_registry.get(rule_id, context.project_id)
        current.pop("bindings", None)
        current.update(request.model_dump(exclude={"expectedRevision"}, exclude_none=True))
        current["ruleId"] = rule_id
        return rule_registry.upsert(current, expected_revision=_expected_revision(request.expectedRevision), **_mutation_identity(context, http_request))
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})
    except RuleValidationError as exc:
        raise _rule_error(exc)


@app.delete("/aiyoloapi/projects/{project_id}/rules/{rule_id}", status_code=204)
@app.delete("/aiyoloapi/rules/{rule_id}", status_code=204, include_in_schema=False)
async def delete_rule(rule_id: str, http_request: Request, expectedRevision: int = Query(ge=1), context: ProjectContext = Depends(require_project_capability(PROJECT_RULES_MANAGE)), project_id: str | None = None):
    try:
        rule_registry.delete(rule_id, expected_revision=expectedRevision, **_mutation_identity(context, http_request))
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})
    except RuleConflict as exc:
        raise _rule_error(exc)


@app.get("/aiyoloapi/projects/{project_id}/rules/{rule_id}/bindings")
@app.get("/aiyoloapi/rules/{rule_id}/bindings", include_in_schema=False)
async def list_rule_bindings(rule_id: str, context: ProjectContext = Depends(require_project_capability(PROJECT_READ)), project_id: str | None = None):
    try:
        return {"projectId": context.project_id, "bindings": rule_registry.bindings(rule_id, context.project_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})


@app.post("/aiyoloapi/projects/{project_id}/rules/{rule_id}/bindings")
@app.post("/aiyoloapi/rules/{rule_id}/bindings", include_in_schema=False)
async def bind_rule(rule_id: str, request: RuleBindingRequest, http_request: Request, context: ProjectContext = Depends(require_project_capability(PROJECT_RULES_MANAGE)), project_id: str | None = None):
    try:
        model_id, capabilities = _rule_source(context, request.sourceId, request.modelId)
        result = rule_registry.bind(rule_id, request.sourceId, capabilities, model_id=model_id, expected_revision=_expected_revision(request.expectedRevision), **_mutation_identity(context, http_request))
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})
    except RuleValidationError as exc:
        raise _rule_error(exc)
    if not result.get("accepted", False):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.post("/aiyoloapi/projects/{project_id}/rules/{rule_id}/validate")
@app.post("/aiyoloapi/rules/{rule_id}/validate", include_in_schema=False)
async def validate_rule_binding(rule_id: str, request: RuleValidationRequest, context: ProjectContext = Depends(require_project_capability(PROJECT_RULES_MANAGE)), project_id: str | None = None):
    """Dry-run a binding; unlike evaluation, incompatibility is never silent."""
    try:
        model_id, capabilities = _rule_source(context, request.sourceId, request.modelId)
        return rule_registry.check(rule_id, request.sourceId, capabilities, model_id=model_id, project_id=context.project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})
    except RuleValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


@app.delete("/aiyoloapi/projects/{project_id}/rules/{rule_id}/bindings/{source_id}")
async def unbind_rule(project_id: str, rule_id: str, source_id: str, http_request: Request,
    expectedRevision: int = Query(ge=1), context: ProjectContext = Depends(require_project_capability(PROJECT_RULES_MANAGE))):
    try:
        return rule_registry.unbind(rule_id, source_id, expected_revision=expectedRevision,
                                    **_mutation_identity(context, http_request))
    except (KeyError, RuleValidationError) as exc:
        raise _rule_error(exc)


def _rule_source(context, source_id, requested_model=None):
    stream = streams.get((context.project_id, source_id))
    config = stream_config_store.get(source_id, context.project_id)
    if stream is None and config is None:
        raise HTTPException(404, detail={"code": "source_not_found", "message": "source not found"})
    metadata = stream.model_metadata() if stream is not None else {}
    model_id = metadata.get("modelId") or (config.model_id if config else None)
    if requested_model is not None and requested_model != model_id:
        raise HTTPException(409, detail={"code": "source_model_mismatch", "message": "model does not match this source"})
    # TRACK is reported only when the detector actually produces track IDs.
    caps = set(metadata.get("provides", metadata.get("capabilities", ["BOX"]))) if model_id else set()
    if "BOX" in caps:
        caps.update({"POLYGON_ROI", "LINE_ROI"})
    return model_id, caps


@app.get("/aiyoloapi/projects/{project_id}/capabilities/sources")
@app.get("/aiyoloapi/capabilities/sources", include_in_schema=False)
async def list_capability_sources(
    context: ProjectContext = Depends(require_project_capability(PROJECT_STREAMS_VIEW)),
    project_id: str | None = None,
):
    """Expose current stream/model capability projection for the admin page."""
    result = []
    source_ids = {item.stream_id for item in stream_config_store.list(context.project_id)}
    source_ids.update(sid for (pid, sid) in streams if pid == context.project_id)
    for stream_id in sorted(source_ids):
        model_id, caps = _rule_source(context, stream_id)
        result.append({"projectId": context.project_id, "sourceId": stream_id,
                       "modelId": model_id, "capabilities": sorted(caps)})
    return {"sources": result}


# --- Alert delivery (M11-T08) ----------------------------------------------
@app.get("/aiyoloapi/projects/{project_id}/alerts/delivery/status")
@app.get("/aiyoloapi/alerts/delivery/status", include_in_schema=False)
async def alert_delivery_status(
    context: ProjectContext = Depends(require_project_capability(PROJECT_SETTINGS_MANAGE)),
    project_id: str | None = None,
):
    """Expose delivery channel health without exposing provider credentials."""
    return {
        "channels": {
            name: {
                "enabled": True,
                "subscribers": (
                    channel.subscriber_count_for(context.project_id)
                    if hasattr(channel, "subscriber_count_for") else 0
                ),
            }
            for name, channel in alert_delivery.channels.items()
        },
        "projectId": context.project_id,
        "pending": alert_delivery.pending_count(context.project_id),
        "recent": alert_delivery.recent_receipts(50, context.project_id),
    }


@app.post("/aiyoloapi/projects/{project_id}/alerts/test-delivery", status_code=202)
@app.post("/aiyoloapi/alerts/test-delivery", status_code=202, include_in_schema=False)
async def test_alert_delivery(
    request: AlertDeliveryRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_SETTINGS_MANAGE)),
    project_id: str | None = None,
):
    """Schedule a synthetic event for configured channels.

    This endpoint is intended for the management page's test action.  It only
    queues work and returns immediately; adapter failures are reported by the
    delivery status endpoint and never turn into an event-generation failure.
    """
    try:
        delivery_ids = alert_delivery.dispatch(
            request.event, request.channels, project_id=context.project_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "CHANNEL_INVALID", "message": str(exc)})
    return {"accepted": True, "projectId": context.project_id, "deliveryIds": delivery_ids}


async def _alert_websocket(websocket: WebSocket, channel_name: str) -> None:
    """Serve one alert subscription with explicit scope authentication."""
    try:
        context = resolve_websocket_project_context(websocket, PROJECT_ALERTS_READ)
        if context.lifecycle_state != "ACTIVE":
            raise HTTPException(403)
    except HTTPException as exc:
        await websocket.close(
            code=4401 if exc.status_code == 401 else 4404 if exc.status_code == 404 else 4403
        )
        return
    await websocket.accept()
    channel = alert_delivery.channels[channel_name]
    queue = await channel.subscribe(context.project_id)
    receiving = asyncio.create_task(websocket.receive())
    pending = asyncio.create_task(queue.get())
    try:
        while True:
            ready, _ = await asyncio.wait(
                (receiving, pending), timeout=1.0, return_when=asyncio.FIRST_COMPLETED
            )
            if receiving in ready:
                if receiving.result()["type"] == "websocket.disconnect":
                    return
                receiving = asyncio.create_task(websocket.receive())
            # Recheck idle subscriptions and queued deliveries. A membership,
            # session or account revoked after the handshake must not leak one
            # more event. Only the original entry is audited, not every tick.
            try:
                current = resolve_websocket_project_context(websocket, PROJECT_ALERTS_READ, audit=False)
                if current.project_id != context.project_id:
                    raise HTTPException(404)
                if current.lifecycle_state != "ACTIVE":
                    raise HTTPException(403)
            except HTTPException as exc:
                await websocket.close(
                    code=4401 if exc.status_code == 401 else 4404 if exc.status_code == 404 else 4403
                )
                return
            if pending in ready:
                payload = pending.result()
                await websocket.send_json({"type": "alert", "event": payload})
                pending = asyncio.create_task(queue.get())
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        receiving.cancel()
        pending.cancel()
        # ASGI disconnect cancellation must not interrupt subscriber cleanup.
        with CancelScope(shield=True):
            await asyncio.gather(receiving, pending, return_exceptions=True)
            await channel.unsubscribe(queue)


@app.websocket("/aiyoloapi/projects/{project_id}/alerts/ws")
@app.websocket("/aiyoloapi/alerts/ws")
async def management_alerts_ws(websocket: WebSocket):
    """Management page real-time alert push channel."""
    await _alert_websocket(websocket, "management")


@app.websocket("/aiyoloapi/projects/{project_id}/alerts/events")
@app.websocket("/aiyoloapi/alerts/events")
async def management_alerts_events_ws(websocket: WebSocket):
    """Compatibility alias for clients naming the management stream events."""
    await _alert_websocket(websocket, "management")


@app.websocket("/aiyoloapi/projects/{project_id}/alerts/notifications")
@app.websocket("/aiyoloapi/alerts/notifications")
async def app_alert_notifications_ws(websocket: WebSocket):
    """App in-product notifications, independent from detection metadata WS."""
    await _alert_websocket(websocket, "app")


@app.websocket("/aiyoloapi/projects/{project_id}/alerts/app")
@app.websocket("/aiyoloapi/alerts/app")
async def app_alert_notifications_alias_ws(websocket: WebSocket):
    """Compatibility alias for App notification clients."""
    await _alert_websocket(websocket, "app")


# --- Alert disposition and false-positive feedback (M11-T09) --------------
@app.get("/aiyoloapi/projects/{project_id}/alerts")
@app.get("/aiyoloapi/alerts", include_in_schema=False)
async def list_alerts(
    status: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=100),
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_READ)),
    project_id: str | None = None,
):
    return {
        "projectId": context.project_id,
        "events": [public_alert_event(event) for event in alert_disposition_store.list(
            status=status, project_id=context.project_id, limit=limit
        )],
    }


@app.get("/aiyoloapi/projects/{project_id}/alerts/export")
async def export_alert_report(request: Request, project_id: str,
                              context: ProjectContext = Depends(require_project_capability(PROJECT_EXPORTS_CREATE))):
    from .project_reports import export_response
    return await export_response(request, context, alert_disposition_store)


@app.get("/aiyoloapi/projects/{project_id}/alerts/false-positives/export")
@app.get("/aiyoloapi/alerts/false-positives/export", include_in_schema=False)
async def export_false_positives(
    request: Request,
    context: ProjectContext = Depends(require_project_capability(PROJECT_EXPORTS_CREATE)),
    project_id: str | None = None,
):
    from .project_reports import export_response
    return await export_response(request, context, alert_disposition_store, feedback=True)


@app.post("/aiyoloapi/projects/{project_id}/alerts/mobile-ingest", status_code=202)
@app.post("/aiyoloapi/alerts/mobile-ingest", status_code=202, include_in_schema=False)
async def ingest_mobile_alert(
    request: MobileAlertIngestRequest,
    http_request: Request,
    context: ProjectContext = Depends(require_alert_ingest),
    project_id: str | None = None,
):
    """Human inspection or explicitly capability-scoped machine ingestion."""
    contract = http_request.headers.get("X-Mobile-Alert-Contract")
    if contract is not None:
        if contract != "1.0":
            raise HTTPException(400, detail={"code": "invalid_event", "message": "unsupported alert contract"})
        if request.disposition is not None:
            raise HTTPException(422, detail={"code": "invalid_event", "message": "v1 disposition requires the delta route"})

        def unsafe_evidence(value):
            if isinstance(value, dict):
                return any(key.lower() in {"snapshotdataurl", "localpath", "objectkey", "objectstorage", "base64"}
                           or unsafe_evidence(child) for key, child in value.items())
            if isinstance(value, list):
                return any(unsafe_evidence(child) for child in value)
            return isinstance(value, str) and (value.strip().lower().startswith(("data:", "file:"))
                or (not value.startswith("/aiyoloapi/projects/")
                    and bool(re.match(r"^(?:[A-Za-z]:[\\/]|/|\\\\)", value))))

        if unsafe_evidence(request.evidence):
            raise HTTPException(422, detail={"code": "invalid_evidence", "message": "v1 evidence must not contain image bytes, local paths or object keys"})
    try:
        assert_ingest_envelope(request, context)
    except HTTPException as exc:
        audit_ingest(context, http_request, request.eventId, error=exc)
        raise
    service = isinstance(context.principal, ServicePrincipal)
    service_digest = hashlib.sha256(json.dumps(
        request.model_dump(exclude={"projectId"}), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode()).hexdigest() if service else None
    if service:
        try:
            existing = alert_disposition_store.get(request.eventId, context.project_id)
        except KeyError:
            existing = None
        if existing is not None:
            if (existing.get("servicePrincipalId") != context.principal.service_principal_id
                    or existing.get("serviceIngestDigest") != service_digest):
                exc = HTTPException(409, detail={"code": "service_event_conflict"})
                audit_ingest(context, http_request, request.eventId, error=exc)
                raise exc
            audit_ingest(context, http_request, request.eventId, created=False)
            return {"accepted": True, "created": False, "eventId": request.eventId, "projectId": context.project_id}
    if request.confirmedAtUs is not None and request.confirmedAtUs < request.startedAtUs:
        raise HTTPException(status_code=422, detail={
            "code": "invalid_event_timestamps", "message": "confirmedAtUs must not be before startedAtUs",
        })
    if request.lastSeenAtUs < request.startedAtUs:
        raise HTTPException(status_code=422, detail={
            "code": "invalid_event_timestamps", "message": "lastSeenAtUs must not be before startedAtUs",
        })

    evidence = dict(request.evidence)
    snapshot_data_url = evidence.pop("snapshotDataUrl", None)
    if snapshot_data_url is not None:
        if not isinstance(snapshot_data_url, str) or not re.match(
            r"^data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=\r\n]+$",
            snapshot_data_url,
            re.IGNORECASE,
        ):
            raise HTTPException(status_code=422, detail={
                "code": "invalid_evidence", "message": "snapshotDataUrl must be an image data URL",
            })
        if len(snapshot_data_url) > 8_000_000:
            raise HTTPException(status_code=413, detail={
                "code": "evidence_too_large", "message": "snapshotDataUrl exceeds the 8 MB limit",
            })
        if alert_evidence_store.enabled:
            try:
                evidence.update(await asyncio.to_thread(
                    alert_evidence_store.store_data_url,
                    f"{request.eventId}:{service_digest}" if service else request.eventId,
                    snapshot_data_url,
                    context.project_id,
                ))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={
                    "code": "invalid_evidence", "message": str(exc),
                }) from exc
            except EvidenceStorageError as exc:
                raise HTTPException(status_code=503, detail={
                    "code": "evidence_storage_unavailable", "message": str(exc),
                }) from exc
        else:
            # Local development compatibility; production requires MinIO.
            evidence["snapshotUri"] = snapshot_data_url
    evidence.pop("localPath", None)
    mobile_origin = request.origin or (
        "MOBILE_IMAGE"
        if request.sourceId == "camera:back:photo" or request.sourceId.startswith("image:")
        else "MOBILE_CAMERA"
    )
    incoming = {
        "eventId": request.eventId,
        "projectId": context.project_id,
        "origin": mobile_origin,
        "ruleId": request.ruleId,
        "sourceId": request.sourceId,
        "subjectKey": request.subjectKey,
        "label": request.label,
        "state": request.state,
        "severity": request.severity,
        "notifySeverity": request.notifySeverity,
        "startedAtUs": request.startedAtUs,
        "confirmedAtUs": request.confirmedAtUs,
        "lastSeenAtUs": request.lastSeenAtUs,
        "effectiveThresholds": dict(request.effectiveThresholds),
        "detectionResults": request.detectionResults,
        "evidence": evidence,
    }
    if request.provenance is not None:
        incoming["provenance"] = request.provenance.model_dump(exclude_none=True)
        incoming["model"] = request.provenance.model.model_dump()
    if service:
        # Recheck after awaited evidence I/O: revoked/rotated credentials cannot
        # finish a pending write using a stale authenticated context.
        incoming.update(servicePrincipalId=context.principal.service_principal_id, serviceIngestDigest=service_digest)
        # Keep the public evidence URL tied to the actual event, not its object key.
        if evidence.get("objectStorage"):
            evidence["snapshotUri"] = f"/aiyoloapi/projects/{context.project_id}/alerts/{quote(request.eventId, safe='')}/evidence"
        try:
            with ingest_write_guard(http_request) as current_context:
                registered, created = alert_disposition_store.register_service_once(
                    incoming, context.project_id, service_revision=current_context.principal.revision)
        except ValueError as exc:
            failure = HTTPException(409, detail={"code": "service_event_conflict"})
            audit_ingest(context, http_request, request.eventId, error=failure)
            raise failure from exc
        except HTTPException as exc:
            audit_ingest(context, http_request, request.eventId, error=exc)
            raise
        if created:
            try:
                alert_delivery.dispatch(registered, channels=["management"], project_id=context.project_id)
            except ValueError:
                pass
        # Ingest does not grant alert-read or human disposition visibility.
        audit_ingest(context, http_request, request.eventId, created=created)
        return {"accepted": True, "created": created, "eventId": request.eventId, "projectId": context.project_id}
    if contract == "1.0":
        producer_id = http_request.headers.get("X-Mobile-Producer-ID")
        if producer_id is not None:
            try:
                producer_id = str(uuid.UUID(producer_id))
            except ValueError as exc:
                raise HTTPException(422, detail={"code": "invalid_producer_id"}) from exc
            incoming["mobileProducer"] = {"accountId": context.principal.account_id, "producerId": producer_id}
        try:
            registered, created = alert_disposition_store.register_mobile_fact(incoming, context.project_id)
        except ValueError as exc:
            raise HTTPException(409, detail={"code": str(exc), "retryable": False}) from exc
        if created:
            try:
                alert_delivery.dispatch(registered, channels=["management"], project_id=context.project_id)
            except ValueError:
                pass
        return {"accepted": True, "created": created, "event": public_alert_event(registered)}
    try:
        current = alert_disposition_store.get(request.eventId, context.project_id)
    except KeyError:
        current = None
    if current is not None:
        if (incoming.get("provenance") is not None
                and current.get("provenance") != incoming["provenance"]):
            raise HTTPException(409, detail={"code": "event_identity_conflict", "retryable": False})
        merged = dict(current)
        merged.update({key: value for key, value in incoming.items() if value is not None})
        merged_evidence = dict(current.get("evidence") or {})
        merged_evidence.update(evidence)
        merged["evidence"] = merged_evidence
        incoming = merged
    try:
        registered = alert_disposition_store.register(incoming, project_id=context.project_id)
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "event_identity_conflict", "retryable": False}) from exc

    action = request.disposition
    if action is not None:
        existing_disposition = registered.get("disposition") or {}
        is_same_retry = (
            existing_disposition.get("status") == action.status
            and existing_disposition.get("actor") == context.principal.account_id
            and existing_disposition.get("actedAtUs") == action.actedAtUs
        )
        if not is_same_retry:
            try:
                registered = alert_disposition_store.dispose(
                    request.eventId,
                    action.status,
                    context.principal.account_id,
                    acted_at_us=action.actedAtUs,
                    screenshot=action.screenshot or evidence.get("snapshotUri"),
                    evidence=evidence,
                    effective_thresholds=request.effectiveThresholds,
                    detection_results=request.detectionResults,
                    note=action.note,
                    project_id=context.project_id,
                )
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=422, detail={"code": "invalid_mobile_disposition", "message": str(exc)})

    if current is None:
        try:
            alert_delivery.dispatch(
                registered, channels=["management"], project_id=context.project_id
            )
        except ValueError:
            # Delivery is advisory; the event itself has already been accepted.
            pass
    return {"accepted": True, "created": current is None, "event": public_alert_event(registered)}


@app.put("/aiyoloapi/projects/{project_id}/alerts/{event_id}/disposition")
async def update_mobile_alert_disposition(
    event_id: str,
    request: MobileAlertDispositionDeltaRequest,
    http_request: Request,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_DISPOSE)),
    project_id: str | None = None,
):
    header = http_request.headers.get("Idempotency-Key")
    try:
        uuid.UUID(request.operationId)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "invalid_idempotency_key", "retryable": False}) from exc
    if header != request.operationId:
        raise HTTPException(422, detail={"code": "idempotency_key_mismatch", "retryable": False})
    digest = hashlib.sha256(json.dumps(request.model_dump(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    try:
        current = alert_disposition_store.get(event_id, context.project_id)
    except KeyError as exc:
        raise HTTPException(409, detail={
            "code": "event_not_ingested", "message": "alert fact must be accepted first", "retryable": True,
        }) from exc
    note = (f"evidenceUnavailableReason={request.evidenceUnavailableReason}"
            if request.evidenceUnavailableReason else None)
    try:
        result = alert_disposition_store.dispose(
            event_id, request.status, context.principal.account_id, acted_at_us=request.actedAtUs,
            note=note, project_id=context.project_id, operation_id=request.operationId, request_digest=digest,
            expected_revision=request.expectedRevision,
        )
    except ValueError as exc:
        code = str(exc) if str(exc) in {"idempotency_conflict", "disposition_revision_conflict", "disposition_terminal"} else "invalid_disposition"
        raise HTTPException(409 if code != "invalid_disposition" else 422, detail={
            "code": code, "message": str(exc), "retryable": False,
        }) from exc
    return {"eventId": event_id, "projectId": context.project_id, "disposition": result["disposition"],
            "dispositionRevision": result.get("dispositionRevision", 0)}


@app.get("/aiyoloapi/projects/{project_id}/alerts/export/false-positives")
@app.get("/aiyoloapi/alerts/export/false-positives", include_in_schema=False)
async def export_false_positives_alias(
    request: Request,
    context: ProjectContext = Depends(require_project_capability(PROJECT_EXPORTS_CREATE)),
    project_id: str | None = None,
):
    from .project_reports import export_response
    return await export_response(request, context, alert_disposition_store, feedback=True)


@app.get("/aiyoloapi/projects/{project_id}/alerts/{event_id}")
@app.get("/aiyoloapi/alerts/{event_id}", include_in_schema=False)
async def get_alert(
    event_id: str,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_READ)),
    project_id: str | None = None,
):
    try:
        return public_alert_event(alert_disposition_store.get(event_id, context.project_id))
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "alert event not found"})


@app.get("/aiyoloapi/projects/{project_id}/alerts/{event_id}/evidence")
@app.get("/aiyoloapi/alerts/{event_id}/evidence", include_in_schema=False)
async def get_server_alert_evidence(
    event_id: str,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_READ)),
    project_id: str | None = None,
):
    try:
        event = alert_disposition_store.get(event_id, context.project_id)
    except KeyError:
        event = None
    evidence = (event or {}).get("evidence") or {}
    tiered = evidence.get("thumbnail") or {}
    if tiered:
        try:
            version = max((int(value) for value in tiered), default=0)
            if version:
                body = await asyncio.to_thread(
                    alert_disposition_store.read_evidence, event_id, context.project_id,
                    "thumbnail", version,
                    lambda reference: alert_evidence_store.read_tiered(
                        reference, context.project_id, event_id, "thumbnail", version),
                )
                return Response(content=body.content, media_type=body.content_type)
        except EvidenceStorageError as exc:
            raise HTTPException(status_code=503, detail={
                "code": "evidence_storage_unavailable", "message": str(exc),
            }) from exc
    if evidence.get("objectStorage"):
        try:
            body = await asyncio.to_thread(
                alert_evidence_store.read, evidence, context.project_id
            )
        except EvidenceStorageError as exc:
            raise HTTPException(status_code=503, detail={
                "code": "evidence_storage_unavailable", "message": str(exc),
            }) from exc
        return Response(content=body.content, media_type=body.content_type)
    inline_uri = evidence.get("snapshotUri") or evidence.get("snapshotDataUrl") or evidence.get("image")
    if isinstance(inline_uri, str) and inline_uri.startswith("data:image/"):
        try:
            body = AlertEvidenceStore.decode_data_url(inline_uri)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={
                "code": "invalid_evidence", "message": str(exc),
            }) from exc
        return Response(content=body.content, media_type=body.content_type)
    path = server_alert_runtime.evidence_path(event_id, context.project_id)
    if path is None:
        raise HTTPException(status_code=404, detail={"code": "evidence_not_found", "message": "alert evidence not found"})
    return FileResponse(path, media_type="image/jpeg")


@app.post("/aiyoloapi/projects/{project_id}/alerts/{event_id}/evidence")
async def upload_alert_evidence(
    project_id: str,
    event_id: str,
    evidence_type: str = Form(alias="evidenceType"),
    content_version: int = Form(alias="contentVersion", ge=1),
    sha256: str = Form(pattern=r"^[a-f0-9]{64}$"),
    file: UploadFile = File(),
    idempotency_key: str = Header(alias="Idempotency-Key"),
    contract: str = Header(alias="X-Mobile-Alert-Contract"),
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_DISPOSE)),
):
    if contract != "1.0":
        raise HTTPException(400, detail={"code": "invalid_evidence", "message": "X-Mobile-Alert-Contract must be 1.0"})
    try:
        uuid.UUID(idempotency_key)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail={"code": "invalid_evidence", "message": "Idempotency-Key must be a UUID"})
    if evidence_type not in {"thumbnail", "original"}:
        raise HTTPException(422, detail={"code": "invalid_evidence", "message": "evidenceType must be thumbnail or original"})
    max_bytes = 128 * 1024 if evidence_type == "thumbnail" else 5 * 1024 * 1024
    try:
        alert_disposition_store.get(event_id, context.project_id)
    except KeyError:
        raise HTTPException(404, detail={"code": "event_not_found", "message": "alert event not found"})
    content_type = (file.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, detail={"code": "unsupported_media_type", "message": "only JPEG, PNG and WebP are accepted"})
    content = bytearray()
    while True:
        chunk = await file.read(min(64 * 1024, max_bytes + 1 - len(content)))
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(413, detail={"code": "evidence_too_large", "message": "evidence exceeds the type-specific byte limit"})
    try:
        normalized_type = AlertEvidenceStore.validate_image(bytes(content), content_type)
    except ValueError as exc:
        raise HTTPException(415, detail={"code": "unsupported_media_type", "message": str(exc)}) from exc
    try:
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != sha256:
            raise ValueError("sha256 does not match uploaded file")
        # Avoid writing a known conflicting version. The store repeats this check atomically
        # when attaching, covering concurrent requests from separate workers.
        existing = alert_disposition_store.get(event_id, context.project_id).get("evidence", {}).get(evidence_type, {}).get(str(content_version))
        if existing and existing.get("sha256") != sha256:
            raise HTTPException(409, detail={"code": "evidence_version_conflict", "message": "content version already has different bytes"})
        if existing:
            return JSONResponse(status_code=200, content={
                "eventId": event_id,
                "evidence": {key: existing[key] for key in
                             ("type", "contentVersion", "sha256", "contentType", "byteLength", "uri")},
            })
        object_storage = await asyncio.to_thread(
            alert_evidence_store.store_tiered_bytes, context.project_id, event_id,
            evidence_type, content_version, bytes(content), normalized_type, sha256,
        )
        reference = {"type": evidence_type, "contentVersion": content_version,
                     "sha256": sha256, "contentType": normalized_type,
                     "byteLength": len(content), "objectStorage": object_storage,
                     "uri": (f"/aiyoloapi/projects/{quote(context.project_id, safe='')}/alerts/"
                            f"{quote(event_id, safe='')}/evidence/{evidence_type}/{content_version}")}
        try:
            _, created = alert_disposition_store.register_evidence(
                event_id, context.project_id, evidence_type, content_version, reference)
        except Exception:
            await asyncio.to_thread(alert_evidence_store.remove_tiered, object_storage)
            raise
    except HTTPException:
        raise
    except ValueError as exc:
        if str(exc) == "evidence_version_conflict":
            raise HTTPException(409, detail={"code": str(exc), "message": "content version already has different bytes"}) from exc
        code = "digest_mismatch" if "sha256" in str(exc) else "invalid_evidence"
        raise HTTPException(422, detail={"code": code, "message": str(exc)}) from exc
    except EvidenceStorageError as exc:
        raise HTTPException(503, detail={"code": "storage_unavailable", "message": str(exc), "retryable": True}) from exc
    except KeyError as exc:
        # Keep missing event distinct from internal missing reference fields.
        if str(exc) == event_id:
            raise HTTPException(404, detail={"code": "event_not_found", "message": "alert event not found"}) from exc
        raise
    response_evidence = {key: reference[key] for key in
                         ("type", "contentVersion", "sha256", "contentType", "byteLength", "uri")}
    return JSONResponse(status_code=201 if created else 200,
                        content={"eventId": event_id, "evidence": response_evidence})


@app.get("/aiyoloapi/projects/{project_id}/alerts/{event_id}/evidence/{evidence_type}/{content_version}")
async def get_tiered_alert_evidence(
    event_id: str,
    evidence_type: str,
    content_version: int,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_READ)),
    project_id: str | None = None,
):
    if evidence_type not in {"thumbnail", "original"} or content_version < 1:
        raise HTTPException(404, detail={"code": "evidence_not_found", "message": "alert evidence not found"})
    try:
        event = alert_disposition_store.get(event_id, context.project_id)
    except KeyError:
        raise HTTPException(404, detail={"code": "event_not_found", "message": "alert event not found"})
    try:
        body = await asyncio.to_thread(
            alert_disposition_store.read_evidence, event_id, context.project_id,
            evidence_type, content_version,
            lambda reference: alert_evidence_store.read_tiered(
                reference, context.project_id, event_id, evidence_type, content_version),
        )
    except EvidenceStorageError as exc:
        raise HTTPException(503, detail={"code": "evidence_storage_unavailable", "message": str(exc)}) from exc
    except KeyError:
        raise HTTPException(404, detail={"code": "evidence_not_found", "message": "alert evidence not found"})
    return Response(content=body.content, media_type=body.content_type)


@app.get("/aiyoloapi/projects/{project_id}/alerts/{event_id}/verification")
@app.get("/aiyoloapi/alerts/{event_id}/verification", include_in_schema=False)
async def get_alert_verification(
    event_id: str,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_READ)),
    project_id: str | None = None,
):
    try:
        alert_disposition_store.get(event_id, context.project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "alert event not found"})
    return alert_verification_store.get(event_id, context.project_id) or {
        "eventId": event_id,
        "projectId": context.project_id,
        "status": "UNREVIEWED",
        "verdict": None,
        "reason": "尚未执行多模态复核",
        "source": "NONE",
    }


@app.post("/aiyoloapi/projects/{project_id}/verification/config")
@app.post("/aiyoloapi/verification/config", include_in_schema=False)
async def update_verification_config(
    context: ProjectContext = Depends(require_project_capability(PROJECT_SETTINGS_MANAGE)),
    project_id: str | None = None,
):
    raise HTTPException(410, detail={"code": "verification_retired", "message": "智能复核功能已退役"})


@app.get("/aiyoloapi/projects/{project_id}/delivery/policy")
async def get_delivery_policy(project_id: str, context: ProjectContext = Depends(require_project_capability(PROJECT_READ))):
    return alert_delivery.policy_store.get(context.project_id)


@app.put("/aiyoloapi/projects/{project_id}/delivery/policy")
async def update_delivery_policy(project_id: str, request: DeliveryPolicyRequest, http_request: Request,
    context: ProjectContext = Depends(require_project_capability(PROJECT_SETTINGS_MANAGE))):
    try:
        return alert_delivery.policy_store.save(context.project_id,
            request.model_dump(exclude={"expectedRevision"}), request.expectedRevision, context=context,
            request_id=http_request.headers.get("x-request-id", "")[:128] or None)
    except DeliveryPolicyConflict as exc:
        raise HTTPException(409, detail={"code": "revision_conflict", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "delivery_policy_invalid", "message": str(exc)})


@app.delete("/aiyoloapi/projects/{project_id}/delivery/policy")
async def reset_delivery_policy(project_id: str, http_request: Request, expectedRevision: int = Query(ge=0),
    context: ProjectContext = Depends(require_project_capability(PROJECT_SETTINGS_MANAGE))):
    store = alert_delivery.policy_store
    try:
        return store.save(context.project_id, store.default(context.project_id), expectedRevision,
            context=context, request_id=http_request.headers.get("x-request-id", "")[:128] or None, reset=True)
    except DeliveryPolicyConflict as exc:
        raise HTTPException(409, detail={"code": "revision_conflict", "message": str(exc)})


@app.get("/aiyoloapi/projects/{project_id}/verification/config")
@app.get("/aiyoloapi/verification/config", include_in_schema=False)
async def get_verification_config(
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_READ)),
    project_id: str | None = None,
):
    raise HTTPException(410, detail={"code": "verification_retired", "message": "智能复核功能已退役"})


@app.post("/aiyoloapi/projects/{project_id}/alerts/{event_id}/verification", status_code=202)
@app.post("/aiyoloapi/alerts/{event_id}/verification", status_code=202, include_in_schema=False)
async def request_alert_verification(
    event_id: str,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_DISPOSE)),
    project_id: str | None = None,
):
    raise HTTPException(status_code=410, detail={"code": "verification_retired", "message": "智能复核功能已退役"})


async def _dispose_alert(
    event_id: str,
    status: str,
    request: AlertDispositionRequest,
    context: ProjectContext,
):
    try:
        result = alert_disposition_store.dispose(
            event_id, status, context.principal.account_id,
            acted_at_us=request.actedAtUs,
            screenshot=request.screenshot, evidence=request.evidence,
            effective_thresholds=request.effectiveThresholds,
            detection_results=request.detectionResults, note=request.note,
            project_id=context.project_id,
            expected_revision=request.expectedRevision,
        )
        return public_alert_event(result)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "alert event not found"})
    except ValueError as exc:
        code = str(exc) if str(exc) in {"disposition_revision_conflict", "disposition_terminal"} else "invalid_disposition"
        raise HTTPException(status_code=409 if code != "invalid_disposition" else 422,
                            detail={"code": code, "message": str(exc), "retryable": False})


@app.post("/aiyoloapi/projects/{project_id}/alerts/{event_id}/acknowledge")
@app.post("/aiyoloapi/alerts/{event_id}/acknowledge", include_in_schema=False)
async def acknowledge_alert(
    event_id: str,
    request: AlertDispositionRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_DISPOSE)),
    project_id: str | None = None,
):
    return await _dispose_alert(event_id, "ACKNOWLEDGED", request, context)


@app.post("/aiyoloapi/projects/{project_id}/alerts/{event_id}/ack")
@app.post("/aiyoloapi/alerts/{event_id}/ack", include_in_schema=False)
async def acknowledge_alert_alias(
    event_id: str,
    request: AlertDispositionRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_DISPOSE)),
    project_id: str | None = None,
):
    return await _dispose_alert(event_id, "ACKNOWLEDGED", request, context)


@app.post("/aiyoloapi/projects/{project_id}/alerts/{event_id}/false-positive")
@app.post("/aiyoloapi/alerts/{event_id}/false-positive", include_in_schema=False)
async def mark_false_positive(
    event_id: str,
    request: AlertDispositionRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_DISPOSE)),
    project_id: str | None = None,
):
    return await _dispose_alert(event_id, "FALSE_POSITIVE", request, context)


@app.post("/aiyoloapi/projects/{project_id}/alerts/{event_id}/mark-false-positive")
@app.post("/aiyoloapi/alerts/{event_id}/mark-false-positive", include_in_schema=False)
async def mark_false_positive_alias(
    event_id: str,
    request: AlertDispositionRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_DISPOSE)),
    project_id: str | None = None,
):
    return await _dispose_alert(event_id, "FALSE_POSITIVE", request, context)


@app.post("/aiyoloapi/projects/{project_id}/alerts/{event_id}/close")
@app.post("/aiyoloapi/alerts/{event_id}/close", include_in_schema=False)
async def close_alert(
    event_id: str,
    request: AlertDispositionRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_DISPOSE)),
    project_id: str | None = None,
):
    return await _dispose_alert(event_id, "CLOSED", request, context)


@app.post("/aiyoloapi/projects/{project_id}/streams", status_code=201)
@app.post("/aiyoloapi/streams", status_code=201, include_in_schema=False)
async def create_stream(
    request: CreateStreamRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_STREAMS_MANAGE)),
    project_id: str | None = None,
):
    project_id = context.project_id
    key = _stream_key(project_id, request.stream_id)
    if key in streams:
        raise HTTPException(status_code=ERROR_CODES["stream_already_exists"][0], detail="stream already exists")
    source = request.source_url
    if isinstance(source, str) and source.isdigit():
        source = int(source)
    stream = StreamSession(
        request.stream_id, source, project_id=project_id, alert_runtime=server_alert_runtime
    )
    stream.model_authorizer = lambda: _runtime_profile(project_id, stream.stream_id, stream.model_catalog_id) is not None
    resolved = _resolve_stream_plan(project_id, request.scene_id, request.plan_id, request.scene_revision)
    selected_member = resolved["members"][0]
    _bind_registered_model(stream, selected_member["modelId"], selected_member["version"], selected_member["parameterSnapshot"])
    configuration = _stream_configuration(
        stream,
        display_name=request.display_name,
        source_type=request.source_type,
        enabled=request.enabled,
        scene_id=request.scene_id,
        plan_id=request.plan_id,
        scene_revision=resolved["revision"],
    )
    created_new_config = True
    try:
        stored = await asyncio.to_thread(stream_config_store.create, configuration)
    except StreamConfigConflict:
        created_new_config = False
        try:
            stored = await asyncio.to_thread(stream_config_store.get, request.stream_id, project_id)
        except Exception as exc:
            raise _storage_error(exc) from exc
        requested_source = str(source) if source is not None else None
        matches = bool(
            stored
            and stored.source_url == requested_source
            and (request.display_name is None or stored.display_name == request.display_name)
            and (request.source_type is None or stored.source_type == request.source_type)
            and stored.scene_id == request.scene_id
            and stored.plan_id == request.plan_id
            and stored.scene_revision == request.scene_revision
            and stored.enabled == request.enabled
        )
        if not matches:
            raise HTTPException(status_code=ERROR_CODES["stream_already_exists"][0], detail="stream already exists")
        try:
            stream = await _session_from_configuration(stored)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "stream_start_failed", "message": "persisted stream could not be started"},
            ) from exc
    except Exception as exc:
        raise _storage_error(exc) from exc
    streams[key] = stream
    if created_new_config:
        try:
            if request.enabled:
                await stream.start()
        except Exception:
            streams.pop(key, None)
            await asyncio.to_thread(stream_config_store.delete, request.stream_id, project_id)
            await stream.close()
            raise
    return {
        "stream_id": stream.stream_id,
        "state": stream.state,
        "yolo_enabled": stream.yolo_enabled,
        "model": stream.model_metadata(),
        **stored.public(),
    }


@app.get("/aiyoloapi/projects/{project_id}/streams")
@app.get("/aiyoloapi/streams", include_in_schema=False)
async def list_streams(
    context: ProjectContext = Depends(require_project_capability(PROJECT_STREAMS_VIEW)),
    project_id: str | None = None,
):
    project_id = context.project_id
    try:
        configurations = await asyncio.to_thread(stream_config_store.list, project_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    payload = [
        _stream_payload(item, streams.get(_stream_key(project_id, item.stream_id)))
        for item in configurations
    ]
    configured_ids = {item.stream_id for item in configurations}
    for stream in streams.values():
        if stream.project_id != project_id or stream.stream_id in configured_ids:
            continue
        payload.append(_stream_payload(_stream_configuration(stream, enabled=not stream.closed), stream))
    return payload


@app.delete("/aiyoloapi/projects/{project_id}/streams/{stream_id}", status_code=204)
@app.delete("/aiyoloapi/streams/{stream_id}", status_code=204, include_in_schema=False)
async def delete_stream(
    stream_id: str,
    context: ProjectContext = Depends(require_project_capability(PROJECT_STREAMS_MANAGE)),
    project_id: str | None = None,
):
    project_id = context.project_id
    key = _stream_key(project_id, stream_id)
    stream = streams.get(key)
    try:
        deleted = await asyncio.to_thread(stream_config_store.delete, stream_id, project_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if stream is None and not deleted:
        raise HTTPException(status_code=404, detail="stream not found")
    if stream is not None:
        await stream.close()
    streams.pop(key, None)
    stream_restore_errors.pop(key, None)


@app.post("/aiyoloapi/projects/{project_id}/streams/{stream_id}/yolo")
@app.post("/aiyoloapi/streams/{stream_id}/yolo", include_in_schema=False)
async def set_yolo(
    stream_id: str,
    request: YoloRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_STREAMS_MANAGE)),
    project_id: str | None = None,
):
    project_id = context.project_id
    key = _stream_key(project_id, stream_id)
    stream = streams.get(key)
    try:
        current = await asyncio.to_thread(stream_config_store.get, stream_id, project_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if stream is None and current is None:
        raise HTTPException(status_code=404, detail="stream not found")
    if request.enabled:
        if current is None or not current.model_id:
            raise HTTPException(409, detail={"code": "scene_plan_required", "message": "stream has no approved scene plan"})
        if not current.model_version:
            raise HTTPException(409, detail={"code": "model_version_required", "message": "stream model version must be pinned"})
        resolved = _resolve_stream_plan(project_id, current.scene_id, current.plan_id, current.scene_revision)
        member = resolved["members"][0]
        if (member["modelId"], member["version"]) != (current.model_id, current.model_version):
            raise HTTPException(409, detail={"code": "scene_plan_model_changed", "message": "scene plan selection is stale"})
    if stream is None:
        try:
            stored = await asyncio.to_thread(
                stream_config_store.update, stream_id, project_id=project_id, yolo_enabled=request.enabled
            )
        except Exception as exc:
            raise _storage_error(exc) from exc
        payload = _stream_payload(stored, None)
        return {
            "project_id": project_id,
            "stream_id": stream_id,
            "state": payload["state"],
            "yolo_enabled": stored.yolo_enabled,
            "overlay_enabled": stored.overlay_enabled,
            "model_error": None,
            "model": payload["model"],
        }
    previous = stream.yolo_enabled
    await stream.set_yolo(request.enabled)
    try:
        await asyncio.to_thread(
            stream_config_store.update, stream_id, project_id=project_id, yolo_enabled=stream.yolo_enabled
        )
    except StreamConfigNotFound as exc:
        await stream.set_yolo(previous)
        raise HTTPException(status_code=409, detail={"code": "stream_config_missing", "message": "stream configuration is missing"}) from exc
    except Exception as exc:
        await stream.set_yolo(previous)
        raise _storage_error(exc) from exc
    return {
        "project_id": project_id,
        "stream_id": stream_id,
        "state": stream.state,
        "yolo_enabled": stream.yolo_enabled,
        "overlay_enabled": stream.overlay_enabled,
        "model_error": stream.detector.load_error,
        "model": stream.model_metadata(),
    }


@app.patch("/aiyoloapi/projects/{project_id}/streams/{stream_id}/config")
@app.patch("/aiyoloapi/streams/{stream_id}/config", include_in_schema=False)
async def update_stream_config(
    stream_id: str,
    request: StreamConfigRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_STREAMS_MANAGE)),
    project_id: str | None = None,
):
    project_id = context.project_id
    key = _stream_key(project_id, stream_id)
    stream = streams.get(key)
    try:
        current = await asyncio.to_thread(stream_config_store.get, stream_id, project_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if current is None:
        if stream is None:
            raise HTTPException(status_code=404, detail="stream not found")
        raise HTTPException(status_code=409, detail={"code": "stream_config_missing", "message": "stream configuration is missing"})

    changes: dict[str, Any] = {}
    for field in ("confidence", "max_fps", "yolo_enabled", "overlay_enabled", "display_name", "enabled"):
        value = getattr(request, field)
        if value is not None:
            changes[field] = value
    selector_fields = (request.scene_id, request.plan_id, request.scene_revision)
    if any(value is not None for value in selector_fields) and not all(value is not None for value in selector_fields):
        raise HTTPException(422, detail={"code": "scene_plan_incomplete", "message": "sceneId, planId and sceneRevision must be supplied together"})
    selection_changed = all(value is not None for value in selector_fields)
    resolved = None
    if selection_changed or request.enabled is True or request.yolo_enabled is True:
        resolved = _resolve_stream_plan(project_id,
            request.scene_id if selection_changed else current.scene_id,
            request.plan_id if selection_changed else current.plan_id,
            request.scene_revision if selection_changed else current.scene_revision)
        member = resolved["members"][0]
        selected_model = member["modelId"]
        selected_version = member["version"]
        assignment = {"modelVersion": selected_version}
        changes.update(model_id=selected_model, model_version=selected_version,
                       scene_id=resolved["sceneId"], plan_id=resolved["planId"],
                       scene_revision=resolved["revision"])
        approved_profile = member["parameterSnapshot"]
        approved_confidence = approved_profile["detection"]["confidenceThreshold"]
        if request.confidence is not None and request.confidence != approved_confidence:
            raise HTTPException(409, detail={"code": "parameter_approval_required", "message": "stream confidence is controlled by approved model parameters"})
        try:
            model_catalog.resolve_server_model(selected_model, assignment["modelVersion"])
        except KeyError:
            raise HTTPException(404, detail={"code": "model_not_found", "message": "model not found"})
        except ValueError:
            raise HTTPException(409, detail={"code": "model_not_available", "message": "model is unavailable"})
        changes["confidence"] = approved_confidence
    else:
        selected_model = current.model_id
        assignment = None
    if resolved is None and request.confidence is not None:
        resolved = _resolve_stream_plan(project_id, current.scene_id, current.plan_id, current.scene_revision)
        member = resolved["members"][0]
        selected_model = member["modelId"]
        assignment = {"modelVersion": member["version"]}
        if request.confidence != member["parameterSnapshot"]["detection"]["confidenceThreshold"]:
            raise HTTPException(409, detail={"code": "parameter_approval_required", "message": "stream confidence is controlled by approved scene parameters"})

    if stream is None:
        try:
            stored = await asyncio.to_thread(
                stream_config_store.update, stream_id, project_id=project_id, **changes
            )
        except Exception as exc:
            if isinstance(exc, StreamConfigNotFound):
                raise HTTPException(status_code=404, detail="stream not found") from exc
            raise _storage_error(exc) from exc
        if request.enabled is True:
            try:
                stream = await _session_from_configuration(stored)
                streams[key] = stream
                stream_restore_errors.pop(key, None)
            except HTTPException:
                await asyncio.to_thread(
                    stream_config_store.update, stream_id, project_id=project_id, enabled=current.enabled
                )
                raise
            except Exception as exc:
                await asyncio.to_thread(
                    stream_config_store.update, stream_id, project_id=project_id, enabled=current.enabled
                )
                stream_restore_errors[key] = "persisted stream could not be restored"
                raise HTTPException(
                    status_code=503,
                    detail={"code": "stream_start_failed", "message": "video stream could not be enabled"},
                ) from exc
        return _stream_payload(stored, stream)

    old_confidence = stream.detector.confidence
    old_max_fps = stream.max_fps
    old_yolo_enabled = stream.yolo_enabled
    old_overlay_enabled = stream.overlay_enabled
    old_detector = stream.detector
    old_model = (stream.model_catalog_id, stream.model_version, stream.model_scenario)
    if request.confidence is not None and not (selected_model or current.model_id):
        stream.detector.confidence = request.confidence
    if request.max_fps is not None:
        await stream.set_max_fps(request.max_fps)
    if request.yolo_enabled is not None:
        await stream.set_yolo(request.yolo_enabled)
    if request.overlay_enabled is not None:
        stream.overlay_enabled = request.overlay_enabled
    if resolved is not None:
        _bind_registered_model(stream, selected_model, assignment["modelVersion"], resolved["members"][0]["parameterSnapshot"])
    try:
        stored = await asyncio.to_thread(
            stream_config_store.update, stream_id, project_id=project_id, **changes
        )
    except Exception as exc:
        stream.detector = old_detector
        stream.detector.confidence = old_confidence
        stream.model_catalog_id, stream.model_version, stream.model_scenario = old_model
        stream.overlay_enabled = old_overlay_enabled
        await stream.set_yolo(old_yolo_enabled)
        await stream.set_max_fps(old_max_fps)
        if isinstance(exc, StreamConfigNotFound):
            raise HTTPException(status_code=409, detail={"code": "stream_config_missing", "message": "stream configuration is missing"}) from exc
        raise _storage_error(exc) from exc
    if request.enabled is False and not stream.closed:
        await stream.close()
    elif request.enabled is True and (stream.closed or not current.enabled):
        try:
            replacement = await _session_from_configuration(stored)
        except HTTPException:
            await asyncio.to_thread(
                stream_config_store.update, stream_id, project_id=project_id, enabled=False
            )
            raise
        except Exception as exc:
            await asyncio.to_thread(
                stream_config_store.update, stream_id, project_id=project_id, enabled=False
            )
            stream_restore_errors[key] = "persisted stream could not be restored"
            raise HTTPException(
                status_code=503,
                detail={"code": "stream_start_failed", "message": "video stream could not be enabled"},
            ) from exc
        await stream.close()
        streams[key] = replacement
        stream = replacement
        stream_restore_errors.pop(key, None)
    return {
        **_stream_payload(stored, stream),
        "model_error": stream.detector.load_error,
    }


@app.put("/aiyoloapi/projects/{project_id}/streams/{stream_id}/model")
@app.put("/aiyoloapi/streams/{stream_id}/model", include_in_schema=False)
async def bind_stream_model(
    stream_id: str,
    request: StreamModelRequest,
    context: ProjectContext = Depends(require_project_capability(PROJECT_STREAMS_MANAGE)),
    project_id: str | None = None,
):
    project_id = context.project_id
    stream = streams.get(_stream_key(project_id, stream_id))
    try:
        current = await asyncio.to_thread(stream_config_store.get, stream_id, project_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if stream is None and current is None:
        raise HTTPException(status_code=404, detail="stream not found")
    resolved = _resolve_stream_plan(project_id, request.scene_id, request.plan_id, request.scene_revision)
    member = resolved["members"][0]
    model_id, version = member["modelId"], member["version"]
    profile = member["parameterSnapshot"]
    if stream is None:
        try:
            model_catalog.resolve_server_model(model_id, version)
        except KeyError:
            raise HTTPException(status_code=404, detail={"code": "model_not_found", "message": "model not found"})
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "model_not_available", "message": str(exc)})
        try:
            await asyncio.to_thread(
                stream_config_store.update, stream_id, project_id=project_id, model_id=model_id,
                model_version=version, confidence=profile["detection"]["confidenceThreshold"],
                scene_id=request.scene_id, plan_id=request.plan_id, scene_revision=resolved["revision"]
            )
        except Exception as exc:
            raise _storage_error(exc) from exc
        return {
            "project_id": project_id,
            "stream_id": stream_id,
            "scene_id": request.scene_id, "plan_id": request.plan_id,
            "scene_revision": resolved["revision"], "model": _configured_model(model_id, version),
        }
    old_detector = stream.detector
    old_model = (stream.model_catalog_id, stream.model_version, stream.model_scenario)
    model = _bind_registered_model(stream, model_id, version, profile)
    try:
        await asyncio.to_thread(
            stream_config_store.update, stream_id, project_id=project_id, model_id=model_id,
            model_version=version, confidence=profile["detection"]["confidenceThreshold"],
            scene_id=request.scene_id, plan_id=request.plan_id, scene_revision=resolved["revision"]
        )
    except Exception as exc:
        stream.detector = old_detector
        stream.model_catalog_id, stream.model_version, stream.model_scenario = old_model
        if isinstance(exc, StreamConfigNotFound):
            raise HTTPException(status_code=409, detail={"code": "stream_config_missing", "message": "stream configuration is missing"}) from exc
        raise _storage_error(exc) from exc
    return {"project_id": project_id, "stream_id": stream_id, "scene_id": request.scene_id,
            "plan_id": request.plan_id, "scene_revision": resolved["revision"], "model": model}


@app.get("/aiyoloapi/projects/{project_id}/streams/{stream_id}/model")
@app.get("/aiyoloapi/streams/{stream_id}/model", include_in_schema=False)
async def stream_model(
    stream_id: str,
    context: ProjectContext = Depends(require_project_capability(PROJECT_STREAMS_VIEW)),
    project_id: str | None = None,
):
    """Return the model binding and registry metadata for one stream."""
    project_id = context.project_id
    stream = streams.get(_stream_key(project_id, stream_id))
    if stream is not None:
        return {"project_id": project_id, "stream_id": stream_id, "model": stream.model_metadata()}
    try:
        configuration = await asyncio.to_thread(stream_config_store.get, stream_id, project_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if configuration is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return {
        "project_id": project_id,
        "stream_id": stream_id,
        "model": _configured_model(configuration.model_id, configuration.model_version),
    }


@app.websocket("/aiyoloapi/projects/{project_id}/streams/{stream_id}/ingest")
@app.websocket("/aiyoloapi/streams/{stream_id}/ingest")
async def ingest(stream_id: str, websocket: WebSocket):
    try:
        context = resolve_ingest_context(websocket, STREAMS_INGEST)
    except HTTPException as exc:
        await websocket.close(code=4401 if exc.status_code == 401 else 4404 if exc.status_code == 404 else 4403)
        return
    stream = streams.get(_stream_key(context.project_id, stream_id))
    if stream is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    pending_receive = None
    try:
        while True:
            if pending_receive is None:
                pending_receive = asyncio.create_task(websocket.receive())
            done, _ = await asyncio.wait({pending_receive}, timeout=1.0)
            # Re-authorize even idle sockets, and before processing every frame.
            try:
                context = resolve_ingest_context(websocket, STREAMS_INGEST, recheck=True)
            except HTTPException as exc:
                await websocket.close(code=4401 if exc.status_code == 401 else 4404 if exc.status_code == 404 else 4403)
                return
            if not done:
                continue
            message = pending_receive.result()
            pending_receive = None
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await stream.ingest_jpeg(message["bytes"])
            elif message.get("text"):
                await websocket.send_text(json.dumps({"ok": True}))
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception as exc:
        code = 4429 if isinstance(exc, InputRateLimitError) else 4400
        # Exceptions may contain connection strings, provider details or
        # attacker-controlled payloads. Do not publish them to peers/status.
        reason = "ingest rate limit exceeded" if code == 4429 else "ingest failed"
        stream.last_error = reason
        await websocket.close(code=code, reason=reason)
    finally:
        if pending_receive is not None:
            pending_receive.cancel()
            await asyncio.gather(pending_receive, return_exceptions=True)


async def require_admin_preview_context(request: Request) -> ProjectContext:
    # PC uses the existing HttpOnly same-origin login cookie. Bearer-only mobile
    # sessions, service tokens and the retired generic playback routes do not
    # obtain this capability. This is a channel boundary, not device detection.
    if (not request.cookies.get(SESSION_COOKIE) or request.headers.get("authorization")
            or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}):
        raise HTTPException(status_code=403, detail={"code": "admin_preview_session_required",
                            "message": "Use the same-origin admin login session for preview."})
    if not request.path_params.get("project_id"):
        raise project_context_required_error()
    return await require_project_capability(PROJECT_STREAMS_VIEW)(request)


@app.get("/aiyoloapi/projects/{project_id}/streams/{stream_id}/preview")
async def admin_stream_preview(
    project_id: str, stream_id: str, request: Request,
    context: ProjectContext = Depends(require_admin_preview_context),
):
    """On-demand PC snapshot, with authorization on every request and response."""
    headers = {"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff",
               "Cross-Origin-Resource-Policy": "same-origin"}
    stream = streams.get(_stream_key(context.project_id, stream_id))
    if stream is None or stream.closed:
        raise HTTPException(status_code=404, detail="stream not found", headers=headers)
    snapshot = await stream.admin_preview()
    # Revoke access even if membership/session changed during JPEG encoding.
    principal = authenticate(request)
    if principal is None or principal.legacy:
        raise authentication_error()
    refreshed = resolve_project_context(principal, context.project_id)
    if PROJECT_STREAMS_VIEW not in refreshed.capabilities:
        raise HTTPException(status_code=403, detail={"code": "capability_required",
                            "message": "Project preview access is no longer available."})
    if stream.closed or streams.get(_stream_key(context.project_id, stream_id)) is not stream:
        raise HTTPException(status_code=404, detail="stream not found", headers=headers)
    if snapshot is None:
        return Response(status_code=204, headers=headers)
    payload, mode = snapshot
    return Response(payload, media_type="image/jpeg", headers={**headers, "X-Preview-Mode": mode})


def live_video_retired():
    raise HTTPException(
        status_code=410,
        detail={"code": "live_video_retired", "message": "Live video distribution is retired; use project alerts."},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/aiyoloapi/projects/{project_id}/streams/{stream_id}/mjpeg", include_in_schema=False)
@app.get("/aiyoloapi/streams/{stream_id}/mjpeg", include_in_schema=False)
@app.get("/aiyoloapi/projects/{project_id}/streams/{stream_id}/playback", include_in_schema=False)
@app.get("/aiyoloapi/streams/{stream_id}/playback", include_in_schema=False)
async def retired_live_video(stream_id: str, project_id: str | None = None):
    # Deliberately do not resolve a stream: missing/existing/foreign IDs reveal nothing.
    live_video_retired()


@app.websocket("/aiyoloapi/projects/{project_id}/streams/{stream_id}/ws")
@app.websocket("/aiyoloapi/streams/{stream_id}/ws")
@app.websocket("/aiyoloapi/projects/{project_id}/streams/{stream_id}/detections")
@app.websocket("/aiyoloapi/streams/{stream_id}/detections")
async def retired_live_websocket(stream_id: str, websocket: WebSocket):
    await websocket.close(code=1008, reason="live_video_retired")


from .alerts.mobile_control_api import create_mobile_control_router
app.include_router(create_mobile_control_router(alert_disposition_store))
