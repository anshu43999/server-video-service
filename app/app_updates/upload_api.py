"""Authenticate before consuming multipart bytes; never spool unbounded forms."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import time

from fastapi import APIRouter, HTTPException, Request
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header
from starlette.requests import ClientDisconnect
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse

from .apk_verifier import ApkVerifier, Toolchain
from .minio_store import ApkMinioStore
from .uploads import ApkUploads, UploadError
from .verification_jobs import BuildCompatibility
from .api import RequestBudget
from .service import UpdateError
from .security import current_admin


def configured_uploads(database, settings):
    try:
        if not 0 < settings.app_apk_receive_seconds < settings.app_apk_lease_seconds:
            raise ValueError("invalid receive/lease limits")
        compatibility = BuildCompatibility(**json.loads(Path(settings.app_apk_compatibility_path).read_text(encoding="utf-8")))
        compatibility.validate()
        return ApkUploads(database, ApkVerifier(Toolchain.from_settings(settings)), ApkMinioStore.from_settings(settings),
            root=settings.app_apk_upload_root, compatibility=compatibility, max_jobs=settings.app_apk_max_jobs,
            lease_seconds=settings.app_apk_lease_seconds)
    except Exception as exc:
        raise UploadError("apk_upload_not_configured", 503) from exc


class MultipartApk:
    def __init__(self, boundary, output, max_bytes):
        self.output, self.max_bytes = output, max_bytes
        self.size, self.digest = 0, hashlib.sha256()
        self.fields, self.seen = {}, set()
        self.ended = False
        callbacks = {name: getattr(self, name) for name in (
            "on_part_begin", "on_header_field", "on_header_value", "on_header_end",
            "on_headers_finished", "on_part_data", "on_part_end", "on_end")}
        self.parser = MultipartParser(boundary, callbacks, max_header_count=4, max_header_size=2048)

    def on_part_begin(self):
        self.headers, self.header_name, self.header_value = {}, bytearray(), bytearray()
        self.field, self.value = None, bytearray()

    def on_header_field(self, data, start, end):
        self.header_name.extend(data[start:end])

    def on_header_value(self, data, start, end):
        self.header_value.extend(data[start:end])

    def on_header_end(self):
        name = bytes(self.header_name).lower()
        if name in self.headers:
            raise UploadError("invalid_multipart", 422)
        self.headers[name] = bytes(self.header_value)
        self.header_name.clear()
        self.header_value.clear()

    def on_headers_finished(self):
        disposition, options = parse_options_header(self.headers.get(b"content-disposition", b""))
        name = options.get(b"name")
        if disposition != b"form-data" or name not in (b"apk", b"idempotencyKey", b"reason") or name in self.seen:
            raise UploadError("invalid_upload_fields", 422)
        if (name == b"apk") != (b"filename" in options):
            raise UploadError("invalid_upload_fields", 422)
        # filename is deliberately ignored; only a server UUID selects a path.
        self.seen.add(name)
        self.field = name

    def on_part_data(self, data, start, end):
        block = data[start:end]
        if self.field == b"apk":
            self.size += len(block)
            if self.size > self.max_bytes:
                raise UploadError("apk_too_large", 413)
            self.output.write(block)
            self.digest.update(block)
        else:
            self.value.extend(block)
            if len(self.value) > (128 if self.field == b"idempotencyKey" else 4000):
                raise UploadError("invalid_upload_fields", 422)

    def on_part_end(self):
        if self.field != b"apk":
            self.fields[self.field.decode("ascii")] = self.value.decode("utf-8", errors="strict")

    def on_end(self):
        self.ended = True

    def finish(self):
        self.parser.finalize()
        if not self.ended or self.seen != {b"apk", b"idempotencyKey", b"reason"} or not self.size:
            raise UploadError("incomplete_multipart", 422)
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", self.fields["idempotencyKey"]):
            raise UploadError("invalid_upload_fields", 422)


def create_upload_router(provider, *, max_bytes, receive_seconds, budget=None):
    if not 0 < max_bytes <= 8 * 1024**3 or not 0 < receive_seconds <= 1200:
        raise ValueError("invalid APK receive limits")
    router = APIRouter()
    budget = budget or RequestBudget(rate=30, concurrent=4)

    @router.post("/aiyoloapi/admin/app-updates/artifacts/upload", status_code=202)
    async def upload(request: Request):
        admitted = False
        service, upload_id = None, None
        accepted = False
        code = "upload_interrupted"
        try:
            actor, auth_code = current_admin(request)
            if auth_code:
                raise UploadError(auth_code, 401 if auth_code == "authentication_required" else 403)
            budget.enter(request.client.host if request.client else "unknown")
            admitted = True
            if request.scope.get("query_string", b""):
                raise UploadError("invalid_request", 422)
            content_type, options = parse_options_header(request.headers.get("content-type", ""))
            boundary = options.get(b"boundary", b"")
            if content_type != b"multipart/form-data" or not 1 <= len(boundary) <= 70:
                raise UploadError("invalid_multipart", 422)
            service = provider()
            upload_id = await asyncio.to_thread(service.begin, actor)
            with service.path(upload_id).open("xb") as output:
                form = MultipartApk(boundary, output, max_bytes)
                total, deadline = 0, time.monotonic() + receive_seconds
                iterator = request.stream().__aiter__()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    try:
                        chunk = await asyncio.wait_for(iterator.__anext__(), timeout=min(30, remaining))
                    except StopAsyncIteration:
                        break
                    total += len(chunk)
                    if total > max_bytes + 16384:
                        raise UploadError("apk_too_large", 413)
                    for offset in range(0, len(chunk), 65536):
                        form.parser.write(chunk[offset:offset + 65536])
                form.finish()
                output.flush()
                os.fsync(output.fileno())
            current, auth_code = current_admin(request)
            if auth_code or current != actor:
                raise UploadError(auth_code or "authentication_required", 403 if auth_code == "platform_admin_required" else 401)
            result = await asyncio.to_thread(service.finish, upload_id,
                idempotency_key=form.fields["idempotencyKey"], reason=form.fields["reason"],
                size_bytes=form.size, sha256=form.digest.hexdigest(), actor=current)
            accepted = True
            return JSONResponse(result, status_code=202, headers={"Cache-Control": "no-store"})
        except UploadError as exc:
            code = exc.code
            raise HTTPException(exc.status, detail={"code": code}, headers={"Cache-Control": "no-store",
                **({"Retry-After": "60"} if exc.status == 429 else {})}) from None
        except UpdateError:
            code = "rate_limited"
            raise HTTPException(429, detail={"code": code}, headers={"Cache-Control": "no-store", "Retry-After": "60"}) from None
        except TimeoutError:
            code = "upload_timeout"
            raise HTTPException(408, detail={"code": code}, headers={"Cache-Control": "no-store"}) from None
        except (ValueError, UnicodeError, ClientDisconnect):
            code = "invalid_multipart"
            raise HTTPException(422, detail={"code": code}, headers={"Cache-Control": "no-store"}) from None
        except OSError:
            code = "apk_staging_unavailable"
            raise HTTPException(503, detail={"code": code}, headers={"Cache-Control": "no-store"}) from None
        except SQLAlchemyError:
            code = "service_unavailable"
            raise HTTPException(503, detail={"code": code}, headers={"Cache-Control": "no-store"}) from None
        finally:
            try:
                if service and upload_id and not accepted:
                    await asyncio.to_thread(service.fail_receive, upload_id, code)
            except SQLAlchemyError:
                # Durable receiving lease is recovered after DB availability.
                # Never let a cleanup exception expose SQL/connection details.
                pass
            finally:
                if admitted:
                    budget.leave()

    return router
