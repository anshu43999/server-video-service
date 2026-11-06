"""Small JSON registration requests; jobs download from third parties directly."""
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import ClientDisconnect

from .apk_verifier import ApkVerifier, Toolchain
from .contract import ExternalArtifactRequest, SourceRequest
from .external_fetch import ExternalFetcher
from .external_jobs import ExternalJobs
from .uploads import UploadError
from .verification_jobs import BuildCompatibility
from .api import RequestBudget
from .service import UpdateError
from .signatures import strict_json
from .security import current_admin


def configured_external(database, settings):
    try:
        if settings.app_apk_external_seconds >= settings.app_apk_lease_seconds:
            raise ValueError("external deadline must precede lease")
        compatibility = BuildCompatibility(**json.loads(Path(settings.app_apk_compatibility_path).read_text(encoding="utf-8")))
        compatibility.validate()
        return ExternalJobs(database, ApkVerifier(Toolchain.from_settings(settings)), ExternalFetcher(
            max_bytes=settings.app_apk_max_bytes, seconds=settings.app_apk_external_seconds),
            root=settings.app_apk_external_root, compatibility=compatibility,
            max_jobs=settings.app_apk_max_jobs, lease_seconds=settings.app_apk_lease_seconds)
    except Exception as exc:
        raise UploadError("external_apk_not_configured", 503) from exc


def create_external_router(provider, *, budget=None):
    router = APIRouter()
    budget = budget or RequestBudget(rate=30, concurrent=4)

    async def register(request, target=None):
        admitted = False
        try:
            actor, code = current_admin(request)
            if code:
                raise UploadError(code, 401 if code == "authentication_required" else 403)
            budget.enter(request.client.host if request.client else "unknown")
            admitted = True
            if request.scope.get("query_string", b""):
                raise UploadError("invalid_request", 422)
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise UploadError("invalid_request", 422)
            raw = bytearray()
            async with asyncio.timeout(30):
                async for block in request.stream():
                    raw.extend(block)
                    if len(raw) > 16384:
                        raise UploadError("request_too_large", 413)
            model = SourceRequest if target else ExternalArtifactRequest
            strict_json(bytes(raw))
            body = model.model_validate_json(bytes(raw))
            service = provider()
            current, code = current_admin(request)
            if code or current != actor:
                raise UploadError(code or "authentication_required", 403 if code == "platform_admin_required" else 401)
            result = await asyncio.to_thread(service.register, actor, body, target_artifact_id=target)
            return JSONResponse(result, status_code=202, headers={"Cache-Control": "no-store"})
        except UploadError as exc:
            raise HTTPException(exc.status, detail={"code": exc.code}, headers={"Cache-Control": "no-store",
                **({"Retry-After": "60"} if exc.status == 429 else {})}) from None
        except UpdateError:
            raise HTTPException(429, detail={"code": "rate_limited"},
                headers={"Cache-Control": "no-store", "Retry-After": "60"}) from None
        except (ValidationError, ValueError, RecursionError, ClientDisconnect):
            # FastAPI's default validation response can echo URL input. Keep
            # rejected URL credentials/query strings out of every error body.
            raise HTTPException(422, detail={"code": "invalid_request"}, headers={"Cache-Control": "no-store"}) from None
        except TimeoutError:
            raise HTTPException(408, detail={"code": "request_timeout"}, headers={"Cache-Control": "no-store"}) from None
        except SQLAlchemyError:
            raise HTTPException(503, detail={"code": "service_unavailable"}, headers={"Cache-Control": "no-store"}) from None
        finally:
            if admitted:
                budget.leave()

    @router.post("/aiyoloapi/admin/app-updates/external-artifacts", status_code=202)
    async def external(request: Request):
        return await register(request)

    @router.post("/aiyoloapi/admin/app-updates/artifacts/{artifact_id}/download-sources", status_code=202)
    async def source(artifact_id: str, request: Request):
        return await register(request, artifact_id)

    return router
