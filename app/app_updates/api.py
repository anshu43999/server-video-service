"""Bounded public metadata requests and current-platform-admin release APIs."""
import asyncio
import json
from pathlib import Path
import threading
import time
from collections import OrderedDict, deque
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from . import contract as c
from .delivery import configured_tickets
from .publisher import AppPublisher
from .service import AppUpdates, UpdateError
from .signatures import strict_json
from .security import current_admin


class RequestBudget:
    """Bounded process-local admission; forwarded IP headers are not trusted."""
    def __init__(self, rate=120, peers=4096, concurrent=16):
        self.rate, self.peers, self.concurrent = rate, peers, concurrent
        self.entries, self.lock, self.active = OrderedDict(), threading.Lock(), 0

    def enter(self, peer):
        clock = time.monotonic()
        with self.lock:
            events = self.entries.get(peer)
            if events is None:
                if len(self.entries) >= self.peers:
                    oldest, values = next(iter(self.entries.items()))
                    if values and values[-1] > clock - 60:
                        raise UpdateError("rate_limited")
                    del self.entries[oldest]
                events = self.entries[peer] = deque()
            self.entries.move_to_end(peer)
            while events and events[0] <= clock - 60:
                events.popleft()
            if len(events) >= self.rate or self.active >= self.concurrent:
                raise UpdateError("rate_limited")
            events.append(clock)
            self.active += 1

    def leave(self):
        with self.lock:
            self.active -= 1


def configured_updates(database, settings):
    try:
        if not settings.app_updates_enabled or not database.enabled:
            raise ValueError("App updates disabled")
        scopes = json.loads(Path(settings.app_update_scopes_path).read_text(encoding="utf-8"))
        evidence_path = settings.app_update_recovery_evidence_path
        evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8")) if evidence_path else []
        if not isinstance(evidence, list) or len(evidence) > 1000 or any(not isinstance(v, dict) for v in evidence):
            raise ValueError("invalid trusted recovery evidence")
        service = AppUpdates(database, AppPublisher.from_settings(settings), scopes=scopes, recovery_evidence=evidence,
            server_contract_version=settings.app_update_server_contract_version,
            gate_capabilities=settings.app_update_gate_capabilities.split(",") if settings.app_update_gate_capabilities else (),
            max_devices=settings.app_update_max_devices,
            max_receipts_per_device=settings.app_update_max_receipts_per_device,
            tickets=configured_tickets(settings))
        service.upload_enabled = settings.app_apk_worker_enabled
        service.external_enabled = settings.app_apk_external_enabled
        service.max_apk_bytes = settings.app_apk_max_bytes
        return service
    except Exception:
        raise UpdateError("service_unavailable") from None


def create_update_router(provider, *, budget=None):
    router = APIRouter()
    budget = budget or RequestBudget()

    def error(code, request_id):
        status, retryable = c.ERRORS[code]
        return JSONResponse(c.ErrorBody(code=code, message=code, requestId=request_id,
            retryable=retryable).model_dump(), status_code=status,
            headers={"Cache-Control": "no-store", **({"Retry-After": "60"} if status == 429 else {})})

    def admin(request):
        actor, code = current_admin(request)
        if code:
            raise UpdateError(code)
        return actor

    async def post(request, model, method, *, administrative=False, release_id=None, status=200):
        request_id = str(uuid4())
        admitted = False
        actor, body, service = None, None, None
        try:
            actor = admin(request) if administrative else None
            budget.enter(request.client.host if request.client else "unknown")
            admitted = True
            if request.query_params:
                raise UpdateError("invalid_request")
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise UpdateError("invalid_request")
            raw = bytearray()
            async with asyncio.timeout(15):
                async for block in request.stream():
                    if len(raw) + len(block) > 65536:
                        raise UpdateError("invalid_request")
                    raw.extend(block)
            data = strict_json(bytes(raw))
            if isinstance(data, dict) and data.get("contractVersion", c.CONTRACT_VERSION) != c.CONTRACT_VERSION:
                raise UpdateError("contract_unsupported")
            body = model.model_validate_json(bytes(raw))
            request_id = getattr(body, "requestId", request_id)
            if release_id is not None and body.releaseId != release_id:
                raise UpdateError("invalid_request")
            service = provider()
            if administrative and admin(request) != actor:
                raise UpdateError("authentication_required")
            args = (actor, body) if administrative else (body,)
            result = await asyncio.to_thread(getattr(service, method), *args)
            return JSONResponse(result, status_code=status, headers={"Cache-Control": "no-store"})
        except UpdateError as exc:
            if administrative and method != "rollback_preview" and service is not None:
                try:
                    await asyncio.to_thread(service.rejected, actor, body, method, exc.code)
                except SQLAlchemyError:
                    pass
            return error(exc.code, request_id)
        except (ValidationError, ValueError, RecursionError, TimeoutError):
            return error("invalid_request", request_id)
        except SQLAlchemyError:
            return error("service_unavailable", request_id)
        finally:
            if admitted:
                budget.leave()

    @router.post("/aiyoloapi/mobile/app-updates/check")
    async def check(request: Request):
        return await post(request, c.CheckRequest, "check")

    @router.post("/aiyoloapi/mobile/app-updates/{release_id}/download-ticket")
    async def download(release_id: str, request: Request):
        return await post(request, c.DownloadRequest, "download", release_id=release_id)

    @router.post("/aiyoloapi/mobile/app-updates/{release_id}/install-permission")
    async def install(release_id: str, request: Request):
        return await post(request, c.InstallPermissionRequest, "install", release_id=release_id)

    @router.post("/aiyoloapi/mobile/app-updates/receipts")
    async def receipt(request: Request):
        return await post(request, c.Receipt, "receipt")

    @router.post("/aiyoloapi/admin/app-updates/releases", status_code=201)
    async def draft(request: Request):
        return await post(request, c.ReleaseDraftRequest, "draft", administrative=True, status=201)

    @router.post("/aiyoloapi/admin/app-updates/releases/{release_id}/publish")
    async def publish(release_id: str, request: Request):
        return await post(request, c.PublishRequest, "publish", administrative=True, release_id=release_id)

    @router.post("/aiyoloapi/admin/app-updates/releases/{release_id}/stop")
    async def stop(release_id: str, request: Request):
        return await post(request, c.StopRequest, "stop", administrative=True, release_id=release_id)

    @router.post("/aiyoloapi/admin/app-updates/rollback-preview")
    async def rollback_preview(request: Request):
        return await post(request, c.RollbackPreviewRequest, "rollback_preview", administrative=True)

    @router.post("/aiyoloapi/admin/app-updates/rollbacks", status_code=202)
    async def rollback_apply(request: Request):
        return await post(request, c.RollbackRequest, "rollback_apply", administrative=True, status=202)

    @router.get("/aiyoloapi/admin/app-updates/rollbacks/{operation_id}")
    async def rollback_operation(operation_id: str, request: Request):
        admitted = False
        try:
            actor = admin(request)
            budget.enter(request.client.host if request.client else "unknown")
            admitted = True
            if request.query_params:
                raise UpdateError("invalid_request")
            result = await asyncio.to_thread(provider().rollback_read, actor, operation_id)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except UpdateError as exc:
            return error(exc.code, str(uuid4()))
        except SQLAlchemyError:
            return error("service_unavailable", str(uuid4()))
        finally:
            if admitted:
                budget.leave()

    async def read(request, kind, **kwargs):
        request_id = str(uuid4())
        admitted = False
        try:
            actor = admin(request)
            budget.enter(request.client.host if request.client else "unknown")
            admitted = True
            if set(request.query_params) - {"limit", "cursor"}:
                raise UpdateError("invalid_request")
            limit = int(request.query_params.get("limit", "50"))
            result = await asyncio.to_thread(provider().read, actor, kind, limit=limit,
                cursor=request.query_params.get("cursor"), **kwargs)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except UpdateError as exc:
            return error(exc.code, request_id)
        except ValueError:
            return error("invalid_request", request_id)
        except SQLAlchemyError:
            return error("service_unavailable", request_id)
        finally:
            if admitted:
                budget.leave()

    @router.get("/aiyoloapi/admin/app-updates/artifacts")
    async def artifacts(request: Request):
        return await read(request, "artifacts")

    @router.get("/aiyoloapi/admin/app-updates/configuration")
    async def configuration(request: Request):
        admitted = False
        try:
            actor = admin(request)
            budget.enter(request.client.host if request.client else "unknown")
            admitted = True
            if request.query_params:
                raise UpdateError("invalid_request")
            result = await asyncio.to_thread(provider().configuration, actor)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except UpdateError as exc:
            return error(exc.code, str(uuid4()))
        except SQLAlchemyError:
            return error("service_unavailable", str(uuid4()))
        finally:
            if admitted:
                budget.leave()

    @router.get("/aiyoloapi/admin/app-updates/artifacts/{artifact_id}")
    async def artifact(artifact_id: str, request: Request):
        return await read(request, "artifacts", resource_id=artifact_id)

    @router.get("/aiyoloapi/admin/app-updates/artifacts/{artifact_id}/download-sources")
    async def sources(artifact_id: str, request: Request):
        return await read(request, "sources", artifact_id=artifact_id)

    @router.get("/aiyoloapi/admin/app-updates/releases")
    async def releases(request: Request):
        return await read(request, "releases")

    @router.get("/aiyoloapi/admin/app-updates/releases/{release_id}")
    async def release(release_id: str, request: Request):
        return await read(request, "releases", resource_id=release_id)

    @router.get("/aiyoloapi/admin/app-updates/audit")
    async def audit(request: Request):
        return await read(request, "audit")

    return router
