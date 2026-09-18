from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .stream import StreamSession
from .protocol import ERROR_CODES, InputRateLimitError, StreamState
from .auth import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    authenticate,
    authenticate_websocket,
    authentication_error,
    create_auth_router,
    require_admin,
    require_catalog_access,
    require_mobile,
)
from .config import settings
from .database import database
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
from .model_parameters import ModelParameterConflict, ModelParameterError, ModelParameterStore
from .conversion import ConversionService
from .conversion_api import create_conversion_router
from .alerts.rules import RuleValidationError, rule_registry
from .alerts.disposition import alert_disposition_store
from .alerts.verification import AlertVerificationStore, alert_verification_store
from .alerts.delivery import AlertDeliveryService
from .alerts.runtime import ServerAlertRuntime

streams: dict[str, StreamSession] = {}
stream_config_store = StreamConfigStore(database if database.enabled else None)
stream_restore_errors: dict[str, str] = {}
model_catalog = ModelCatalog()
model_parameter_store = ModelParameterStore(database_manager=database if database.enabled else None)
conversion_service = ConversionService(
    model_catalog.project_root / "models" / "local-conversion",
    database_manager=database if database.enabled else None,
)
alert_verification_store.configure_database(database if database.enabled else None)
alert_delivery = AlertDeliveryService(database_manager=database if database.enabled else None)
server_alert_runtime = ServerAlertRuntime(
    model_provider=model_catalog.get,
    parameter_store=model_parameter_store,
    event_store=alert_disposition_store,
    delivery_service=alert_delivery,
    evidence_root=model_catalog.project_root / "evidence" / "server-alerts",
)
dashboard_stats = DashboardStatsService(
    database if database.enabled else None,
    alert_disposition_store,
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
    stream_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    source_url: str | int | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    source_type: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    enabled: bool = True


class YoloRequest(BaseModel):
    enabled: bool


class StreamConfigRequest(BaseModel):
    confidence: float | None = Field(default=None, ge=0.01, le=0.99)
    max_fps: float | None = Field(default=None, ge=1, le=60)
    yolo_enabled: bool | None = None
    overlay_enabled: bool | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None


class StreamModelRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)


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
    sourceId: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list)
    modelId: str | None = None


class AlertDispositionRequest(BaseModel):
    """Human disposition payload; actor is taken from the authenticated header."""
    actedAtUs: int | None = Field(default=None, ge=0)
    screenshot: str | None = Field(default=None, max_length=2048)
    evidence: dict | None = None
    effectiveThresholds: dict | None = None
    detectionResults: list | dict | None = None
    note: str | None = Field(default=None, max_length=1000)


class MobileAlertDispositionRequest(BaseModel):
    """A local App action carried with the event ingest request."""

    status: Literal["ACKNOWLEDGED", "FALSE_POSITIVE"]
    actor: str = Field(min_length=1, max_length=128)
    actedAtUs: int = Field(ge=0)
    screenshot: str | None = Field(default=None, max_length=8_000_000)
    note: str | None = Field(default=None, max_length=1000)


class MobileAlertIngestRequest(BaseModel):
    """Portable event envelope produced by the Android local alert pipeline."""

    eventId: str = Field(min_length=1, max_length=256, pattern=r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
    ruleId: str = Field(min_length=1, max_length=128)
    sourceId: str = Field(min_length=1, max_length=128)
    origin: Literal["MOBILE_CAMERA", "MOBILE_IMAGE"] | None = None
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


class AlertVerificationRequest(BaseModel):
    image: str | None = Field(default=None, max_length=2048)
    note: str | None = Field(default=None, max_length=1000)


class VerificationConfigRequest(BaseModel):
    enabled: bool = False
    imageEgressAuthorized: bool = False
    dailyLimit: int = Field(default=100, ge=0, le=10000)
    modelId: str = Field(default="", max_length=128)
    providerConfigured: bool = False


class RuleValidationRequest(BaseModel):
    sourceId: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list)
    modelId: str | None = None


class RulePatchRequest(BaseModel):
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
    model_catalog.validate_startup()
    await asyncio.to_thread(database.verify_schema)
    try:
        conversion_service.start()
        await restore_stream_sessions()
        yield
    finally:
        await asyncio.to_thread(conversion_service.close)
        await asyncio.to_thread(database.close)
        await alert_delivery.close()
        await asyncio.gather(*(stream.close() for stream in streams.values()), return_exceptions=True)
        streams.clear()


app = FastAPI(title="Server Video Service", version="0.1.0", lifespan=lifespan)
app.include_router(create_auth_router())
app.include_router(create_conversion_router(conversion_service, model_catalog))
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/admin", StaticFiles(directory=STATIC_DIR, html=True), name="admin")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(STATIC_DIR / "index.html")


def get_stream(stream_id: str) -> StreamSession:
    stream = streams.get(stream_id)
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
) -> StreamConfiguration:
    source = str(stream.source_url) if stream.source_url is not None else None
    return StreamConfiguration(
        stream_id=stream.stream_id,
        display_name=display_name or stream.stream_id,
        source_type=source_type or infer_source_type(stream.source_url),
        source_url=source,
        model_id=stream.model_catalog_id,
        yolo_enabled=stream.yolo_enabled,
        confidence=float(stream.detector.confidence),
        max_fps=float(stream.max_fps),
        overlay_enabled=stream.overlay_enabled,
        enabled=enabled,
    )


def _bind_registered_model(stream: StreamSession, model_id: str) -> dict[str, Any]:
    try:
        item, path = model_catalog.resolve_server_model(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "model_not_found", "message": "model not found"})
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "model_not_available", "message": str(exc)})
    return stream.bind_model(
        model_id=model_id,
        model_path=str(path),
        scenario=item.get("scenario"),
        purpose=item.get("purpose"),
        labels=item.get("labels"),
        imgsz=item.get("inputSize"),
    )


async def _session_from_configuration(configuration: StreamConfiguration) -> StreamSession:
    stream = StreamSession(
        configuration.stream_id,
        configuration.runtime_source(),
        alert_runtime=server_alert_runtime,
    )
    stream.detector.confidence = configuration.confidence
    stream.overlay_enabled = configuration.overlay_enabled
    await stream.set_max_fps(configuration.max_fps)
    if configuration.model_id:
        _bind_registered_model(stream, configuration.model_id)
    await stream.set_yolo(configuration.yolo_enabled)
    if configuration.enabled:
        await stream.start()
    return stream


async def restore_stream_sessions() -> None:
    """Restore enabled control-plane records without making one bad source fatal."""
    configurations = await asyncio.to_thread(stream_config_store.list)
    stream_restore_errors.clear()
    for configuration in configurations:
        if not configuration.enabled or configuration.stream_id in streams:
            continue
        try:
            streams[configuration.stream_id] = await _session_from_configuration(configuration)
        except Exception:
            # Do not expose model paths, source credentials, or driver errors.
            stream_restore_errors[configuration.stream_id] = "persisted stream could not be restored"


def _configured_model(model_id: str | None) -> dict[str, Any]:
    if not model_id:
        return {"modelId": None, "catalog_model_id": None, "name": "unbound"}
    try:
        item = model_catalog.get(model_id)
    except KeyError:
        return {"modelId": model_id, "catalog_model_id": model_id, "name": model_id, "available": False}
    return {
        "modelId": model_id,
        "catalog_model_id": model_id,
        "name": item.get("name") or model_id,
        "scenario": item.get("scenario"),
        "purpose": item.get("purpose"),
        "available": True,
    }


def _stream_payload(configuration: StreamConfiguration, stream: StreamSession | None) -> dict[str, Any]:
    if stream is None:
        runtime_state = "not_started" if configuration.enabled else "disabled"
        restore_error = stream_restore_errors.get(configuration.stream_id)
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
            "publish_state": "idle",
            "viewers": 0,
            "last_error": restore_error,
            "model": _configured_model(configuration.model_id),
        }
    return {
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


@app.get("/api/metrics")
async def metrics(_: None = Depends(require_admin)):
    return {"system": system_metrics(), "streams": {stream_id: stream.metrics() for stream_id, stream in streams.items()}}


@app.get("/api/dashboard/stats")
async def dashboard_statistics(
    range: Literal["today", "7d", "30d"] = Query(default="today"),
    _: None = Depends(require_admin),
):
    """Return persisted dashboard statistics plus current stream telemetry."""
    try:
        return await asyncio.to_thread(dashboard_stats.build, range, streams, system_metrics())
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "dashboard_stats_unavailable", "message": "dashboard statistics are unavailable"},
        ) from exc


@app.get("/api/models")
async def list_models(
    scenario: str | None = Query(default=None, min_length=1, max_length=128),
    _: None = Depends(require_catalog_access),
):
    models = model_catalog.list_models()
    if scenario is not None:
        models = [model for model in models if model.get("scenario") == scenario]
    return {"models": models}


@app.get("/api/models/{model_id}")
async def model_detail(model_id: str, _: None = Depends(require_catalog_access)):
    try:
        model = model_catalog.get(model_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_not_found", "message": "model not found"},
        )
    return model


@app.delete("/api/models/{model_id}")
async def uninstall_model(model_id: str, _: None = Depends(require_admin)):
    runtime_bindings = {
        stream_id
        for stream_id, stream in streams.items()
        if stream.model_catalog_id == model_id
    }
    try:
        persisted_bindings = {
            item.stream_id
            for item in await asyncio.to_thread(stream_config_store.list)
            if item.model_id == model_id
        }
    except Exception as exc:
        raise _storage_error(exc) from exc
    bound_streams = sorted(runtime_bindings | persisted_bindings)
    if bound_streams:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "model_in_use",
                "message": "model is bound to one or more video streams",
                "streamIds": bound_streams,
            },
        )
    try:
        return model_catalog.uninstall(model_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_not_found", "message": "model not found"},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "model_in_use", "message": str(exc)},
        )


def _parameter_model(model_id: str) -> dict:
    try:
        return model_catalog.get(model_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_not_found", "message": "model not found"},
        )


def _parameter_actor(request: Request) -> str:
    actor = request.headers.get("x-operator-id") or request.headers.get("x-actor") or "admin"
    return actor.strip()[:128] or "admin"


@app.get("/api/models/{model_id}/parameters")
async def get_model_parameters(
    model_id: str,
    platform: Literal["android", "server"] = Query(default="android"),
    _: None = Depends(require_catalog_access),
):
    try:
        return model_parameter_store.get(_parameter_model(model_id), platform)
    except ModelParameterError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)})


@app.put("/api/models/{model_id}/parameters")
async def update_model_parameters(
    model_id: str,
    request: ModelParameterRequest,
    http_request: Request,
    platform: Literal["android", "server"] = Query(default="android"),
    _: None = Depends(require_admin),
):
    model = _parameter_model(model_id)
    values = request.model_dump(exclude={"expectedRevision"}, exclude_none=True)
    try:
        return model_parameter_store.save(
            model,
            platform,
            values,
            _parameter_actor(http_request),
            request.expectedRevision,
        )
    except ModelParameterConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    except ModelParameterError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


@app.delete("/api/models/{model_id}/parameters")
async def reset_model_parameters(
    model_id: str,
    http_request: Request,
    platform: Literal["android", "server"] = Query(default="android"),
    _: None = Depends(require_admin),
):
    try:
        return model_parameter_store.reset(
            _parameter_model(model_id),
            platform,
            _parameter_actor(http_request),
        )
    except ModelParameterError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)})


@app.get("/api/models/{model_id}/artifacts/{artifact_id}/download")
async def download_model_artifact(
    model_id: str,
    artifact_id: str,
    request: Request,
    _: None = Depends(require_catalog_access),
):
    """Stream a catalog artifact after an on-disk size/hash revalidation.

    The token is accepted only by the header dependency above.  File paths stay
    server-side; clients receive safe download metadata and the advertised
    SHA-256 in ``X-Model-SHA256`` for an independent post-download check.
    """
    try:
        artifact, path = model_catalog.get_artifact(model_id, artifact_id)
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

    _acquire_model_download(request)
    expected_size = int(artifact["sizeBytes"])
    expected_hash = str(artifact["sha256"])
    content_type = str(artifact.get("contentType") or "application/octet-stream")
    # The basename has already passed the models-root containment check.  Quote
    # it for a standards-compliant header and prevent CR/LF injection.
    safe_name = quote(path.name.replace("\r", "").replace("\n", ""), safe="")

    async def body():
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(max(1024, int(settings.model_download_chunk_size)))
                    if not chunk:
                        break
                    yield chunk
        finally:
            _release_model_download()

    return StreamingResponse(
        body(),
        media_type=content_type,
        headers={
            "Content-Length": str(expected_size),
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}",
            "X-Model-SHA256": expected_hash,
        },
    )


@app.post("/api/models/{model_id}/activate")
async def activate_model(model_id: str, _: None = Depends(require_admin)):
    try:
        model = model_catalog.activate(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"active_model": model}


@app.post("/api/models/register")
async def register_models(request: RegisterManifestRequest, _: None = Depends(require_admin)):
    try:
        models = model_catalog.register_manifest(request.manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"models": models}


# --- Runtime alert rule management (M11-T07) -------------------------------
@app.get("/api/rules")
async def list_rules(_: None = Depends(require_admin)):
    return {"rules": rule_registry.list()}


@app.get("/api/rules/audit")
async def list_rule_audit(rule_id: str | None = Query(default=None), _: None = Depends(require_admin)):
    return {"audit": rule_registry.audits(rule_id)}


@app.get("/api/rules/{rule_id}")
async def get_rule(rule_id: str, _: None = Depends(require_admin)):
    try:
        return rule_registry.get(rule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})


@app.post("/api/rules", status_code=201)
async def create_rule(request: RuleRequest, _: None = Depends(require_admin)):
    try:
        try:
            rule_registry.get(request.ruleId)
            raise HTTPException(status_code=409, detail={"code": "rule_already_exists", "message": "rule already exists"})
        except KeyError:
            pass
        return rule_registry.upsert(request.model_dump(exclude_none=True))
    except RuleValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


@app.put("/api/rules/{rule_id}")
async def update_rule(rule_id: str, request: RuleRequest, _: None = Depends(require_admin)):
    if request.ruleId != rule_id:
        raise HTTPException(status_code=400, detail={"code": "RULE_ID_MISMATCH", "message": "ruleId does not match path"})
    try:
        return rule_registry.upsert(request.model_dump(exclude_none=True))
    except RuleValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


@app.patch("/api/rules/{rule_id}")
async def patch_rule(rule_id: str, request: RulePatchRequest, _: None = Depends(require_admin)):
    try:
        current = rule_registry.get(rule_id)
        current.pop("bindings", None)
        current.update(request.model_dump(exclude_none=True))
        current["ruleId"] = rule_id
        return rule_registry.upsert(current)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})
    except RuleValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


@app.delete("/api/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, _: None = Depends(require_admin)):
    try:
        rule_registry.delete(rule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})


@app.get("/api/rules/{rule_id}/bindings")
async def list_rule_bindings(rule_id: str, _: None = Depends(require_admin)):
    try:
        return {"bindings": rule_registry.bindings(rule_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})


@app.post("/api/rules/{rule_id}/bindings")
async def bind_rule(rule_id: str, request: RuleBindingRequest, _: None = Depends(require_admin)):
    try:
        result = rule_registry.bind(rule_id, request.sourceId, request.capabilities, model_id=request.modelId)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})
    except RuleValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})
    if not result.get("accepted", False):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.post("/api/rules/{rule_id}/validate")
async def validate_rule_binding(rule_id: str, request: RuleValidationRequest, _: None = Depends(require_admin)):
    """Dry-run a binding; unlike evaluation, incompatibility is never silent."""
    try:
        return rule_registry.check(rule_id, request.sourceId, request.capabilities, model_id=request.modelId)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "rule not found"})
    except RuleValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


@app.get("/api/capabilities/sources")
async def list_capability_sources(_: None = Depends(require_admin)):
    """Expose current stream/model capability projection for the admin page."""
    result = []
    for stream_id, stream in streams.items():
        model = stream.model_metadata()
        caps = model.get("capabilities") or ["BOX", "TRACK"] if model.get("modelId") else []
        result.append({"sourceId": stream_id, "modelId": model.get("modelId"), "capabilities": caps})
    return {"sources": result}


# --- Alert delivery (M11-T08) ----------------------------------------------
@app.get("/api/alerts/delivery/status")
async def alert_delivery_status(_: None = Depends(require_admin)):
    """Expose delivery channel health without exposing provider credentials."""
    return {
        "channels": {
            name: {"enabled": True, "subscribers": getattr(channel, "subscriber_count", 0)}
            for name, channel in alert_delivery.channels.items()
        },
        "pending": len(alert_delivery._pending),
        "recent": alert_delivery.recent_receipts(50),
    }


@app.post("/api/alerts/test-delivery", status_code=202)
async def test_alert_delivery(request: AlertDeliveryRequest, _: None = Depends(require_admin)):
    """Schedule a synthetic event for configured channels.

    This endpoint is intended for the management page's test action.  It only
    queues work and returns immediately; adapter failures are reported by the
    delivery status endpoint and never turn into an event-generation failure.
    """
    try:
        delivery_ids = alert_delivery.dispatch(request.event, request.channels)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "CHANNEL_INVALID", "message": str(exc)})
    return {"accepted": True, "deliveryIds": delivery_ids}


async def _alert_websocket(websocket: WebSocket, channel_name: str, required_role: str) -> None:
    """Serve one alert subscription with explicit scope authentication."""
    await websocket.accept()
    if authenticate_websocket(websocket, required_role) is None:
        await websocket.close(code=4401, reason="account session required")
        return
    channel = alert_delivery.channels[channel_name]
    queue = await channel.subscribe()
    try:
        while True:
            payload = await queue.get()
            await websocket.send_json({"type": "alert", "event": payload})
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        await channel.unsubscribe(queue)


@app.websocket("/api/alerts/ws")
async def management_alerts_ws(websocket: WebSocket):
    """Management page real-time alert push channel."""
    await _alert_websocket(websocket, "management", ROLE_ADMIN)


@app.websocket("/api/alerts/events")
async def management_alerts_events_ws(websocket: WebSocket):
    """Compatibility alias for clients naming the management stream events."""
    await _alert_websocket(websocket, "management", ROLE_ADMIN)


@app.websocket("/api/alerts/notifications")
async def app_alert_notifications_ws(websocket: WebSocket):
    """App in-product notifications, independent from detection metadata WS."""
    await _alert_websocket(websocket, "app", ROLE_OPERATOR)


@app.websocket("/api/alerts/app")
async def app_alert_notifications_alias_ws(websocket: WebSocket):
    """Compatibility alias for App notification clients."""
    await _alert_websocket(websocket, "app", ROLE_OPERATOR)


# --- Alert disposition and false-positive feedback (M11-T09) --------------
async def require_alert_view(request: Request) -> None:
    """Read-only alert access accepts either admin or mobile credentials."""
    if authenticate(request) is None:
        raise authentication_error("alert session")


async def require_alert_action(request: Request) -> str:
    """Mutating disposition actions are deliberately admin-only."""
    user = authenticate(request, ROLE_ADMIN)
    if user is None:
        raise HTTPException(status_code=403, detail={"code": "disposition_forbidden", "message": "admin permission required"})
    actor = request.headers.get("x-operator-id") or request.headers.get("x-actor") or user.username
    if not actor.strip():
        raise HTTPException(status_code=400, detail={"code": "operator_required", "message": "X-Operator-Id is required"})
    return actor.strip()


@app.get("/api/alerts")
async def list_alerts(status: str | None = Query(default=None), _: None = Depends(require_alert_view)):
    return {"events": alert_disposition_store.list(status=status)}


@app.get("/api/alerts/false-positives/export")
async def export_false_positives(_: None = Depends(require_alert_view)):
    from fastapi.responses import Response
    return Response(
        content=alert_disposition_store.export_json(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=aiyolo-false-positives.json"},
    )


@app.post("/api/alerts/mobile-ingest", status_code=202)
async def ingest_mobile_alert(request: MobileAlertIngestRequest, _: None = Depends(require_mobile)):
    """Create or update a local App event using the device-scoped write token."""
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
        # A data URL is portable and does not expose the App's private filesystem.
        evidence["snapshotUri"] = snapshot_data_url
    evidence.pop("localPath", None)
    mobile_origin = request.origin or (
        "MOBILE_IMAGE"
        if request.sourceId == "camera:back:photo" or request.sourceId.startswith("image:")
        else "MOBILE_CAMERA"
    )
    incoming = {
        "eventId": request.eventId,
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
    try:
        current = alert_disposition_store.get(request.eventId)
    except KeyError:
        current = None
    if current is not None:
        merged = dict(current)
        merged.update({key: value for key, value in incoming.items() if value is not None})
        merged_evidence = dict(current.get("evidence") or {})
        merged_evidence.update(evidence)
        merged["evidence"] = merged_evidence
        incoming = merged
    registered = alert_disposition_store.register(incoming)

    action = request.disposition
    if action is not None:
        existing_disposition = registered.get("disposition") or {}
        is_same_retry = (
            existing_disposition.get("status") == action.status
            and existing_disposition.get("actor") == action.actor.strip()
            and existing_disposition.get("actedAtUs") == action.actedAtUs
        )
        if not is_same_retry:
            try:
                registered = alert_disposition_store.dispose(
                    request.eventId,
                    action.status,
                    action.actor,
                    acted_at_us=action.actedAtUs,
                    screenshot=action.screenshot or evidence.get("snapshotUri"),
                    evidence=evidence,
                    effective_thresholds=request.effectiveThresholds,
                    detection_results=request.detectionResults,
                    note=action.note,
                )
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=422, detail={"code": "invalid_mobile_disposition", "message": str(exc)})

    if current is None:
        try:
            alert_delivery.dispatch(registered, channels=["management"])
        except ValueError:
            # Delivery is advisory; the event itself has already been accepted.
            pass
    return {"accepted": True, "created": current is None, "event": registered}


@app.get("/api/alerts/export/false-positives")
async def export_false_positives_alias(_: None = Depends(require_alert_view)):
    from fastapi.responses import Response
    return Response(
        content=alert_disposition_store.export_json(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=aiyolo-false-positives.json"},
    )


@app.get("/api/alerts/{event_id}")
async def get_alert(event_id: str, _: None = Depends(require_alert_view)):
    try:
        return alert_disposition_store.get(event_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "alert event not found"})


@app.get("/api/alerts/{event_id}/evidence")
async def get_server_alert_evidence(event_id: str, _: None = Depends(require_alert_view)):
    path = server_alert_runtime.evidence_path(event_id)
    if path is None:
        raise HTTPException(status_code=404, detail={"code": "evidence_not_found", "message": "alert evidence not found"})
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/alerts/{event_id}/verification")
async def get_alert_verification(event_id: str, _: None = Depends(require_alert_view)):
    try:
        alert_disposition_store.get(event_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "alert event not found"})
    return alert_verification_store.get(event_id) or {
        "eventId": event_id,
        "status": "UNREVIEWED",
        "verdict": None,
        "reason": "尚未执行多模态复核",
        "source": "NONE",
    }


@app.post("/api/verification/config")
async def update_verification_config(
    request: VerificationConfigRequest,
    _: str = Depends(require_alert_action),
):
    return alert_verification_store.configure(
        enabled=request.enabled,
        image_egress_authorized=request.imageEgressAuthorized,
        daily_limit=request.dailyLimit,
        model_id=request.modelId,
        provider_configured=request.providerConfigured,
    )


@app.get("/api/verification/config")
async def get_verification_config(_: None = Depends(require_alert_view)):
    return alert_verification_store.config()


@app.post("/api/alerts/{event_id}/verification", status_code=202)
async def request_alert_verification(
    event_id: str,
    request: AlertVerificationRequest,
    actor: str = Depends(require_alert_action),
):
    try:
        event = alert_disposition_store.get(event_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "alert event not found"})
    evidence = event.get("evidence") or {}
    image_ref = request.image or evidence.get("snapshotUri") or evidence.get("image")
    try:
        result = alert_verification_store.request(event, actor=actor, image_ref=image_ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_verification", "message": str(exc)})
    # Keep the original alert and disposition untouched; only attach an annotation.
    event["verification"] = result
    alert_disposition_store.register(event)
    return result


async def _dispose_alert(event_id: str, status: str, request: AlertDispositionRequest, actor: str):
    try:
        return alert_disposition_store.dispose(
            event_id, status, actor, acted_at_us=request.actedAtUs,
            screenshot=request.screenshot, evidence=request.evidence,
            effective_thresholds=request.effectiveThresholds,
            detection_results=request.detectionResults, note=request.note,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "alert event not found"})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_disposition", "message": str(exc)})


@app.post("/api/alerts/{event_id}/acknowledge")
async def acknowledge_alert(event_id: str, request: AlertDispositionRequest, actor: str = Depends(require_alert_action)):
    return await _dispose_alert(event_id, "ACKNOWLEDGED", request, actor)


@app.post("/api/alerts/{event_id}/ack")
async def acknowledge_alert_alias(event_id: str, request: AlertDispositionRequest, actor: str = Depends(require_alert_action)):
    return await _dispose_alert(event_id, "ACKNOWLEDGED", request, actor)


@app.post("/api/alerts/{event_id}/false-positive")
async def mark_false_positive(event_id: str, request: AlertDispositionRequest, actor: str = Depends(require_alert_action)):
    return await _dispose_alert(event_id, "FALSE_POSITIVE", request, actor)


@app.post("/api/alerts/{event_id}/mark-false-positive")
async def mark_false_positive_alias(event_id: str, request: AlertDispositionRequest, actor: str = Depends(require_alert_action)):
    return await _dispose_alert(event_id, "FALSE_POSITIVE", request, actor)


@app.post("/api/alerts/{event_id}/close")
async def close_alert(event_id: str, request: AlertDispositionRequest, actor: str = Depends(require_alert_action)):
    return await _dispose_alert(event_id, "CLOSED", request, actor)


@app.post("/api/streams", status_code=201, dependencies=[Depends(require_admin)])
async def create_stream(request: CreateStreamRequest):
    if request.stream_id in streams:
        raise HTTPException(status_code=ERROR_CODES["stream_already_exists"][0], detail="stream already exists")
    source = request.source_url
    if isinstance(source, str) and source.isdigit():
        source = int(source)
    stream = StreamSession(request.stream_id, source, alert_runtime=server_alert_runtime)
    target_id = request.model_id
    if target_id is None:
        # Existing global activation remains only the default for new sessions.
        active = model_catalog._load().get("activeServerModel")
        if active:
            for entry in model_catalog.list_models():
                if entry.get("active") and entry.get("format") in {"pt", "onnx"}:
                    target_id = entry.get("modelId")
                    break
    if target_id:
        _bind_registered_model(stream, target_id)
    configuration = _stream_configuration(
        stream,
        display_name=request.display_name,
        source_type=request.source_type,
        enabled=request.enabled,
    )
    created_new_config = True
    try:
        stored = await asyncio.to_thread(stream_config_store.create, configuration)
    except StreamConfigConflict:
        created_new_config = False
        try:
            stored = await asyncio.to_thread(stream_config_store.get, request.stream_id)
        except Exception as exc:
            raise _storage_error(exc) from exc
        requested_source = str(source) if source is not None else None
        matches = bool(
            stored
            and stored.source_url == requested_source
            and (request.display_name is None or stored.display_name == request.display_name)
            and (request.source_type is None or stored.source_type == request.source_type)
            and (request.model_id is None or stored.model_id == request.model_id)
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
    streams[request.stream_id] = stream
    if created_new_config:
        try:
            if request.enabled:
                await stream.start()
        except Exception:
            streams.pop(request.stream_id, None)
            await asyncio.to_thread(stream_config_store.delete, request.stream_id)
            await stream.close()
            raise
    return {
        "stream_id": stream.stream_id,
        "state": stream.state,
        "yolo_enabled": stream.yolo_enabled,
        "model": stream.model_metadata(),
        **stored.public(),
    }


@app.get("/api/streams")
async def list_streams(_: None = Depends(require_catalog_access)):
    try:
        configurations = await asyncio.to_thread(stream_config_store.list)
    except Exception as exc:
        raise _storage_error(exc) from exc
    payload = [_stream_payload(item, streams.get(item.stream_id)) for item in configurations]
    configured_ids = {item.stream_id for item in configurations}
    for stream in streams.values():
        if stream.stream_id in configured_ids:
            continue
        payload.append(_stream_payload(_stream_configuration(stream, enabled=not stream.closed), stream))
    return payload


@app.delete("/api/streams/{stream_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_stream(stream_id: str):
    stream = streams.get(stream_id)
    try:
        deleted = await asyncio.to_thread(stream_config_store.delete, stream_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if stream is None and not deleted:
        raise HTTPException(status_code=404, detail="stream not found")
    if stream is not None:
        await stream.close()
    streams.pop(stream_id, None)
    stream_restore_errors.pop(stream_id, None)


@app.post("/api/streams/{stream_id}/yolo", dependencies=[Depends(require_admin)])
async def set_yolo(stream_id: str, request: YoloRequest):
    stream = streams.get(stream_id)
    try:
        current = await asyncio.to_thread(stream_config_store.get, stream_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if stream is None and current is None:
        raise HTTPException(status_code=404, detail="stream not found")
    if stream is None:
        try:
            stored = await asyncio.to_thread(stream_config_store.update, stream_id, yolo_enabled=request.enabled)
        except Exception as exc:
            raise _storage_error(exc) from exc
        payload = _stream_payload(stored, None)
        return {
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
        await asyncio.to_thread(stream_config_store.update, stream_id, yolo_enabled=stream.yolo_enabled)
    except StreamConfigNotFound as exc:
        await stream.set_yolo(previous)
        raise HTTPException(status_code=409, detail={"code": "stream_config_missing", "message": "stream configuration is missing"}) from exc
    except Exception as exc:
        await stream.set_yolo(previous)
        raise _storage_error(exc) from exc
    return {
        "stream_id": stream_id,
        "state": stream.state,
        "yolo_enabled": stream.yolo_enabled,
        "overlay_enabled": stream.overlay_enabled,
        "model_error": stream.detector.load_error,
        "model": stream.model_metadata(),
    }


@app.patch("/api/streams/{stream_id}/config", dependencies=[Depends(require_admin)])
async def update_stream_config(stream_id: str, request: StreamConfigRequest):
    stream = streams.get(stream_id)
    try:
        current = await asyncio.to_thread(stream_config_store.get, stream_id)
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
    if request.model_id is not None:
        try:
            model_catalog.resolve_server_model(request.model_id)
        except KeyError:
            raise HTTPException(status_code=404, detail={"code": "model_not_found", "message": "model not found"})
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "model_not_available", "message": str(exc)})
        changes["model_id"] = request.model_id

    if stream is None:
        try:
            stored = await asyncio.to_thread(stream_config_store.update, stream_id, **changes)
        except Exception as exc:
            if isinstance(exc, StreamConfigNotFound):
                raise HTTPException(status_code=404, detail="stream not found") from exc
            raise _storage_error(exc) from exc
        if request.enabled is True:
            try:
                stream = await _session_from_configuration(stored)
                streams[stream_id] = stream
                stream_restore_errors.pop(stream_id, None)
            except Exception as exc:
                await asyncio.to_thread(stream_config_store.update, stream_id, enabled=current.enabled)
                stream_restore_errors[stream_id] = "persisted stream could not be restored"
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
    old_model = (stream.model_catalog_id, stream.model_scenario, stream.model_purpose)
    if request.confidence is not None:
        stream.detector.confidence = request.confidence
    if request.max_fps is not None:
        await stream.set_max_fps(request.max_fps)
    if request.yolo_enabled is not None:
        await stream.set_yolo(request.yolo_enabled)
    if request.overlay_enabled is not None:
        stream.overlay_enabled = request.overlay_enabled
    if request.model_id is not None:
        _bind_registered_model(stream, request.model_id)
    try:
        stored = await asyncio.to_thread(stream_config_store.update, stream_id, **changes)
    except Exception as exc:
        stream.detector = old_detector
        stream.detector.confidence = old_confidence
        stream.model_catalog_id, stream.model_scenario, stream.model_purpose = old_model
        stream.overlay_enabled = old_overlay_enabled
        await stream.set_yolo(old_yolo_enabled)
        await stream.set_max_fps(old_max_fps)
        if isinstance(exc, StreamConfigNotFound):
            raise HTTPException(status_code=409, detail={"code": "stream_config_missing", "message": "stream configuration is missing"}) from exc
        raise _storage_error(exc) from exc
    if request.enabled is False and not stream.closed:
        await stream.close()
    elif request.enabled is True and stream.closed:
        try:
            replacement = await _session_from_configuration(stored)
        except Exception as exc:
            await asyncio.to_thread(stream_config_store.update, stream_id, enabled=False)
            stream_restore_errors[stream_id] = "persisted stream could not be restored"
            raise HTTPException(
                status_code=503,
                detail={"code": "stream_start_failed", "message": "video stream could not be enabled"},
            ) from exc
        streams[stream_id] = replacement
        stream = replacement
        stream_restore_errors.pop(stream_id, None)
    return {
        **_stream_payload(stored, stream),
        "model_error": stream.detector.load_error,
    }


@app.put("/api/streams/{stream_id}/model", dependencies=[Depends(require_admin)])
async def bind_stream_model(stream_id: str, request: StreamModelRequest):
    stream = streams.get(stream_id)
    try:
        current = await asyncio.to_thread(stream_config_store.get, stream_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if stream is None and current is None:
        raise HTTPException(status_code=404, detail="stream not found")
    if stream is None:
        try:
            model_catalog.resolve_server_model(request.model_id)
        except KeyError:
            raise HTTPException(status_code=404, detail={"code": "model_not_found", "message": "model not found"})
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "model_not_available", "message": str(exc)})
        try:
            await asyncio.to_thread(stream_config_store.update, stream_id, model_id=request.model_id)
        except Exception as exc:
            raise _storage_error(exc) from exc
        return {"stream_id": stream_id, "model": _configured_model(request.model_id)}
    old_detector = stream.detector
    old_model = (stream.model_catalog_id, stream.model_scenario, stream.model_purpose)
    model = _bind_registered_model(stream, request.model_id)
    try:
        await asyncio.to_thread(stream_config_store.update, stream_id, model_id=request.model_id)
    except Exception as exc:
        stream.detector = old_detector
        stream.model_catalog_id, stream.model_scenario, stream.model_purpose = old_model
        if isinstance(exc, StreamConfigNotFound):
            raise HTTPException(status_code=409, detail={"code": "stream_config_missing", "message": "stream configuration is missing"}) from exc
        raise _storage_error(exc) from exc
    return {"stream_id": stream_id, "model": model}


@app.get("/api/streams/{stream_id}/model")
async def stream_model(stream_id: str, _: None = Depends(require_catalog_access)):
    """Return the model binding and registry metadata for one stream."""
    stream = streams.get(stream_id)
    if stream is not None:
        return {"stream_id": stream_id, "model": stream.model_metadata()}
    try:
        configuration = await asyncio.to_thread(stream_config_store.get, stream_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if configuration is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return {"stream_id": stream_id, "model": _configured_model(configuration.model_id)}


@app.websocket("/api/streams/{stream_id}/ingest")
async def ingest(stream_id: str, websocket: WebSocket):
    stream = streams.get(stream_id)
    if stream is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    if authenticate_websocket(websocket, ROLE_OPERATOR) is None:
        await websocket.close(code=4401, reason="mobile session required")
        return
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await stream.ingest_jpeg(message["bytes"])
            elif message.get("text"):
                await websocket.send_text(json.dumps({"ok": True}))
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception as exc:
        stream.last_error = str(exc)
        code = 4429 if isinstance(exc, InputRateLimitError) else 4400
        await websocket.close(code=code, reason=str(exc))


async def mjpeg_generator(stream: StreamSession):
    previous = None
    while not stream.closed:
        frame = await stream.wait_frame(previous)
        if frame is None:
            return
        previous = frame
        yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"


@app.get("/api/streams/{stream_id}/mjpeg")
async def mjpeg(stream_id: str, _: None = Depends(require_catalog_access)):
    stream = get_stream(stream_id)
    if not stream.try_subscribe():
        raise HTTPException(status_code=429, detail="output subscriber limit reached")

    async def guarded_generator():
        try:
            async for frame in mjpeg_generator(stream):
                yield frame
        finally:
            stream.unsubscribe()

    return StreamingResponse(
        guarded_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/streams/{stream_id}/playback")
async def playback(stream_id: str, _: None = Depends(require_catalog_access)):
    """Return WHEP, LL-HLS and diagnostic RTSP playback entries."""
    stream = get_stream(stream_id)
    return {"stream_id": stream.stream_id, **stream.publisher.playback()}


@app.websocket("/api/streams/{stream_id}/ws")
async def output_ws(stream_id: str, websocket: WebSocket):
    stream = streams.get(stream_id)
    if stream is None:
        await websocket.close(code=4404)
        return
    if not stream.try_subscribe():
        await websocket.close(code=4429, reason="output subscriber limit reached")
        return
    await websocket.accept()
    previous = None
    try:
        while True:
            frame = await stream.wait_frame(previous)
            if frame is None:
                return
            previous = frame
            await websocket.send_bytes(frame)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        stream.unsubscribe()


@app.websocket("/api/streams/{stream_id}/detections")
async def detections_ws(stream_id: str, websocket: WebSocket):
    """结构化检测结果旁路（协议 §6.2）。

    该 WebSocket 只发送 JSON 元数据，不依赖视频输出订阅。YOLO 关闭时按固定
    心跳周期发送状态，客户端可独立重连而不影响视频通道。
    """
    stream = streams.get(stream_id)
    if stream is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    if authenticate_websocket(websocket, ROLE_OPERATOR) is None:
        await websocket.close(code=4401, reason="mobile session required")
        return

    heartbeat_interval = 5.0
    last_version = 0
    try:
        while True:
            if not stream.yolo_enabled:
                await websocket.send_text(
                    json.dumps(
                        {"stream_id": stream.stream_id, "yolo_enabled": False},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                await asyncio.sleep(heartbeat_interval)
                continue

            version, detections = await stream.wait_detection(last_version, timeout=heartbeat_interval)
            if stream.closed:
                return
            if detections is not None and version > last_version:
                await websocket.send_text(
                    json.dumps(detections.to_wire(), ensure_ascii=False, separators=(",", ":"))
                )
                last_version = version
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
