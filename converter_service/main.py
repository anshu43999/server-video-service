from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import hmac
import re

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from .config import ConverterSettings, settings
from .jobs import JobStore


class ProtocolError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def public_job(job: dict) -> dict:
    payload = {"jobId": job["jobId"], "status": job["status"]}
    if job["status"] == "succeeded":
        internal = job.get("result") or {}
        allowed = {
            "labels", "input_size", "warmup", "input", "output", "quantization",
            "ultralytics", "sha256", "sizeBytes",
        }
        result = {key: value for key, value in internal.items() if key in allowed}
        result["artifactUrl"] = f"/v1/conversions/{job['jobId']}/artifact"
        payload["result"] = result
    elif job["status"] == "failed":
        payload["error"] = job.get("error") or {
            "code": "conversion_failed", "message": "模型转换失败", "retryable": True
        }
    return payload


def create_app(
    store: JobStore | None = None,
    *,
    token: str | None = None,
    config: ConverterSettings | None = None,
) -> FastAPI:
    config = config or settings
    token = config.token if token is None else token
    job_store = store

    def active_store() -> JobStore:
        if job_store is None:
            raise RuntimeError("converter store is not initialized")
        return job_store

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal job_store
        if len(token) < 24 or any(ord(character) < 33 for character in token):
            raise RuntimeError("CONVERTER_TOKEN must contain at least 24 visible characters")
        if job_store is None:
            job_store = JobStore(
                config.root,
                config.calibration_root,
                timeout_seconds=config.timeout_seconds,
                max_queued_jobs=config.max_queued_jobs,
            )
        job_store.start()
        try:
            yield
        finally:
            job_store.close()

    app = FastAPI(title="AI YOLO Model Converter", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(ProtocolError)
    async def protocol_error(_: Request, exc: ProtocolError):
        return JSONResponse(
            {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
            status_code=exc.status,
        )

    async def authorize(request: Request) -> None:
        authorization = request.headers.get("Authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, token):
            raise ProtocolError(401, "unauthorized", "鉴权失败")

    @app.get("/v1/health", dependencies=[Depends(authorize)])
    async def health():
        return {
            "status": "ok",
            "protocolVersion": 1,
            "capabilities": ["yolo-detect-to-tflite-int8"],
        }

    @app.post("/v1/conversions", dependencies=[Depends(authorize)])
    async def submit(
        request: Request,
        input_size: int = Query(alias="inputSize"),
        calibration_data: str = Query(alias="calibrationData", min_length=1, max_length=512),
    ):
        if input_size not in {320, 416, 640}:
            raise ProtocolError(422, "invalid_request", "inputSize 必须是 320、416 或 640")
        idempotency_key = request.headers.get("Idempotency-Key", "").lower()
        source_hash = request.headers.get("X-Source-SHA256", "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", idempotency_key):
            raise ProtocolError(422, "invalid_request", "Idempotency-Key 无效")
        if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise ProtocolError(422, "invalid_request", "X-Source-SHA256 无效")
        if request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
            raise ProtocolError(415, "unsupported_media_type", "请求体必须是 application/octet-stream")
        store_instance = active_store()
        existing, conflict = store_instance.lookup(idempotency_key, source_hash)
        if conflict:
            raise ProtocolError(409, "idempotency_conflict", "幂等键与源模型不匹配")
        if existing is not None and not (
            existing["status"] == "failed" and (existing.get("error") or {}).get("retryable")
        ):
            return JSONResponse(public_job(existing), status_code=200)
        try:
            store_instance.validate_calibration(calibration_data)
        except ValueError as exc:
            raise ProtocolError(422, "invalid_calibration", "校准数据不可用") from exc

        content_length = request.headers.get("Content-Length")
        if not content_length or not content_length.isdigit():
            raise ProtocolError(411, "length_required", "必须提供 Content-Length")
        declared_size = int(content_length)
        if declared_size <= 0 or declared_size > config.max_upload_bytes:
            raise ProtocolError(413, "upload_too_large", "PT 文件大小超出限制")
        temporary = store_instance.incoming_path()
        digest = hashlib.sha256()
        received = 0
        try:
            with temporary.open("wb") as output:
                async for block in request.stream():
                    received += len(block)
                    if received > declared_size or received > config.max_upload_bytes:
                        raise ProtocolError(413, "upload_too_large", "PT 文件大小超出限制")
                    digest.update(block)
                    output.write(block)
            if received != declared_size:
                raise ProtocolError(422, "invalid_request", "请求体大小与 Content-Length 不一致")
            if digest.hexdigest() != source_hash:
                raise ProtocolError(422, "source_hash_mismatch", "源模型 SHA-256 不匹配")
            try:
                job, queued = store_instance.submit(
                    temporary,
                    source_hash=source_hash,
                    idempotency_key=idempotency_key,
                    input_size=input_size,
                    calibration_data=calibration_data,
                )
            except ValueError as exc:
                if str(exc) == "idempotency_conflict":
                    raise ProtocolError(409, "idempotency_conflict", "幂等键与源模型不匹配") from exc
                raise
            except OverflowError as exc:
                raise ProtocolError(429, "queue_full", "转换队列已满", retryable=True) from exc
            return JSONResponse(public_job(job), status_code=202 if queued else 200)
        finally:
            temporary.unlink(missing_ok=True)

    @app.get("/v1/conversions/{job_id}", dependencies=[Depends(authorize)])
    async def status(job_id: str):
        try:
            return public_job(active_store().get(job_id))
        except KeyError as exc:
            raise ProtocolError(404, "job_not_found", "转换任务不存在") from exc

    @app.delete("/v1/conversions/{job_id}", dependencies=[Depends(authorize)])
    async def cancel(job_id: str):
        try:
            return public_job(active_store().cancel(job_id))
        except KeyError as exc:
            raise ProtocolError(404, "job_not_found", "转换任务不存在") from exc

    @app.get("/v1/conversions/{job_id}/artifact", dependencies=[Depends(authorize)])
    async def artifact(job_id: str):
        try:
            path = active_store().artifact(job_id)
        except (KeyError, FileNotFoundError) as exc:
            raise ProtocolError(404, "artifact_not_found", "转换产物不存在") from exc
        return FileResponse(path, media_type="application/octet-stream", filename="android.tflite")

    return app


app = create_app()
