"""MinIO-backed storage for alert evidence images."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
import re
from typing import Any, Mapping
from urllib.parse import quote, urlparse

from .database import DEFAULT_PROJECT_ID

try:
    from minio import Minio
except ImportError:
    Minio = None  # type: ignore[assignment]


DATA_URL_PATTERN = re.compile(
    r"^data:(image/(?:png|jpeg|jpg|webp));base64,([A-Za-z0-9+/=\r\n]+)$",
    re.IGNORECASE,
)
CONTENT_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}


class EvidenceStorageError(RuntimeError):
    """Configured object storage could not persist or read evidence."""


@dataclass(frozen=True)
class EvidenceBody:
    content: bytes
    content_type: str


class AlertEvidenceStore:
    def __init__(
        self,
        *,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str = "aiyolo-alerts",
        secure: bool = True,
        region: str | None = None,
        prefix: str = "alerts",
        auto_create_bucket: bool = False,
        client: Any = None,
    ) -> None:
        self.endpoint = (endpoint or "").strip()
        self.bucket = bucket.strip()
        self.prefix = prefix.strip(" /") or "alerts"
        self.auto_create_bucket = bool(auto_create_bucket)
        self.enabled = bool(self.endpoint)
        self._client = client
        if not self.enabled:
            return
        if not access_key or not secret_key or not self.bucket:
            raise ValueError("MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY and MINIO_BUCKET are required together")
        parsed = urlparse(self.endpoint if "://" in self.endpoint else f"//{self.endpoint}")
        if parsed.path not in {"", "/"} or not parsed.netloc:
            raise ValueError("MINIO_ENDPOINT must be a host[:port] without a path")
        endpoint_value = parsed.netloc
        if parsed.scheme:
            secure = parsed.scheme.lower() == "https"
        if self._client is None:
            if Minio is None:
                raise RuntimeError("the minio package is required when MINIO_ENDPOINT is configured")
            self._client = Minio(
                endpoint_value,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
                region=region or None,
            )

    @classmethod
    def from_settings(cls, settings: Any) -> "AlertEvidenceStore":
        return cls(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
            region=settings.minio_region,
            prefix=settings.minio_alert_prefix,
            auto_create_bucket=settings.minio_auto_create_bucket,
        )

    def validate(self) -> None:
        if not self.enabled:
            return
        try:
            exists = self._client.bucket_exists(self.bucket)
            if not exists and self.auto_create_bucket:
                self._client.make_bucket(self.bucket)
                exists = True
            if not exists:
                raise EvidenceStorageError(f"MinIO bucket {self.bucket!r} does not exist")
        except EvidenceStorageError:
            raise
        except Exception as exc:
            raise EvidenceStorageError("MinIO bucket validation failed") from exc

    @staticmethod
    def decode_data_url(data_url: str, *, max_bytes: int = 8_000_000) -> EvidenceBody:
        match = DATA_URL_PATTERN.fullmatch(data_url.strip())
        if not match:
            raise ValueError("snapshotDataUrl must be a PNG, JPEG or WebP data URL")
        content_type = match.group(1).lower().replace("image/jpg", "image/jpeg")
        try:
            encoded = re.sub(r"[\r\n]", "", match.group(2))
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("snapshotDataUrl contains invalid base64") from exc
        if not content:
            raise ValueError("snapshotDataUrl is empty")
        if len(content) > max_bytes:
            raise ValueError("snapshotDataUrl exceeds the 8 MB decoded limit")
        return EvidenceBody(content, content_type)

    def store_data_url(self, event_id: str, data_url: str,
                       project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        body = self.decode_data_url(data_url)
        return self.store_bytes(event_id, body.content, body.content_type, project_id)

    def store_bytes(self, event_id: str, content: bytes, content_type: str,
                    project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        if not self.enabled:
            raise EvidenceStorageError("MinIO evidence storage is not configured")
        digest = hashlib.sha256(content).hexdigest()
        event_digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        project_digest = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        extension = CONTENT_EXTENSIONS.get(content_type.lower(), "bin")
        object_key = (
            f"{self.prefix}/projects/{project_digest}/{event_digest[:2]}/"
            f"{event_digest}.{extension}"
        )
        try:
            self._client.put_object(
                self.bucket,
                object_key,
                BytesIO(content),
                len(content),
                content_type=content_type,
                metadata={
                    "project-id-sha256": project_digest,
                    "event-id-sha256": event_digest,
                    "content-sha256": digest,
                },
            )
        except Exception as exc:
            raise EvidenceStorageError("failed to upload alert evidence to MinIO") from exc
        return {
            "snapshotUri": (
                f"/aiyoloapi/projects/{quote(project_id, safe='')}/alerts/"
                f"{quote(event_id, safe='')}/evidence"
            ),
            "objectStorage": {
                "provider": "minio",
                "bucket": self.bucket,
                "objectKey": object_key,
                "contentType": content_type,
                "sizeBytes": len(content),
                "sha256": digest,
            },
        }

    @staticmethod
    def validate_image(content: bytes, declared_type: str) -> str:
        """Validate the declared type against the actual supported image signature."""
        signatures = (
            ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
            ("image/png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
            ("image/webp", lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
        )
        actual = next((kind for kind, check in signatures if check(content)), None)
        if actual is None or declared_type.lower() != actual:
            raise ValueError("file content does not match a supported image MIME type")
        return actual

    def store_tiered_bytes(self, project_id: str, event_id: str, evidence_type: str,
                           content_version: int, content: bytes, content_type: str,
                           digest: str) -> dict[str, Any]:
        if not self.enabled:
            raise EvidenceStorageError("MinIO evidence storage is not configured")
        actual_type = self.validate_image(content, content_type)
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != digest:
            raise ValueError("sha256 does not match uploaded file")
        ext = CONTENT_EXTENSIONS[actual_type]
        identity = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        project_hash = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        key = (f"{self.prefix}/projects/{project_hash}/events/{identity}/"
               f"{evidence_type}/{content_version}/{actual_digest}.{ext}")
        try:
            self._client.put_object(self.bucket, key, BytesIO(content), len(content),
                                    content_type=actual_type,
                                    metadata={"project-id-sha256": project_hash,
                                              "event-id-sha256": identity,
                                              "content-sha256": actual_digest,
                                              "evidence-type": evidence_type,
                                              "content-version": str(content_version)})
        except Exception as exc:
            raise EvidenceStorageError("failed to upload alert evidence to MinIO") from exc
        return {"provider": "minio", "bucket": self.bucket, "objectKey": key,
                "contentType": actual_type, "sizeBytes": len(content), "sha256": actual_digest}

    def read_tiered(self, reference: Mapping[str, Any], project_id: str,
                    event_id: str, evidence_type: str, content_version: int) -> EvidenceBody:
        obj = reference.get("objectStorage") or {}
        if obj.get("provider") != "minio" or obj.get("bucket") != self.bucket:
            raise EvidenceStorageError("alert evidence object reference is invalid")
        project_hash = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        event_hash = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        key = str(obj.get("objectKey") or "")
        digest = str(reference.get("sha256") or "")
        expected = (f"{self.prefix}/projects/{project_hash}/events/{event_hash}/"
                    f"{evidence_type}/{content_version}/{digest}")
        if (re.fullmatch(r"[a-f0-9]{64}", digest) is None
                or re.fullmatch(re.escape(expected) + r"\.(?:jpg|png|webp)", key) is None):
            raise EvidenceStorageError("alert evidence object reference is invalid")
        response = None
        try:
            response = self._client.get_object(self.bucket, key)
            content = response.read()
        except Exception as exc:
            raise EvidenceStorageError("failed to read alert evidence from MinIO") from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()
        return EvidenceBody(content, str(reference.get("contentType") or "application/octet-stream"))

    def remove_tiered(self, object_storage: Mapping[str, Any]) -> None:
        try:
            self._client.remove_object(str(object_storage["bucket"]), str(object_storage["objectKey"]))
        except Exception as exc:
            raise EvidenceStorageError("failed to remove unreferenced alert evidence") from exc

    def read(self, evidence: Mapping[str, Any],
             project_id: str = DEFAULT_PROJECT_ID) -> EvidenceBody:
        reference = evidence.get("objectStorage") or {}
        if reference.get("provider") != "minio":
            raise EvidenceStorageError("alert evidence is not stored in MinIO")
        bucket = str(reference.get("bucket") or "")
        object_key = str(reference.get("objectKey") or "")
        project_digest = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        expected_prefix = f"{self.prefix}/projects/{project_digest}/"
        object_suffix = object_key.removeprefix(expected_prefix)
        if (
            bucket != self.bucket
            or not object_key.startswith(expected_prefix)
            or re.fullmatch(r"[a-f0-9]{2}/[a-f0-9]{64}\.(?:png|jpg|webp|bin)", object_suffix) is None
        ):
            raise EvidenceStorageError("alert evidence object reference is invalid")
        response = None
        try:
            response = self._client.get_object(bucket, object_key)
            content = response.read()
        except Exception as exc:
            raise EvidenceStorageError("failed to read alert evidence from MinIO") from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()
        return EvidenceBody(content, str(reference.get("contentType") or "application/octet-stream"))
