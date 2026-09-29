"""MinIO-backed storage for alert evidence images."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
import re
from typing import Any, Mapping
from urllib.parse import quote, urlparse

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

    def store_data_url(self, event_id: str, data_url: str) -> dict[str, Any]:
        body = self.decode_data_url(data_url)
        return self.store_bytes(event_id, body.content, body.content_type)

    def store_bytes(self, event_id: str, content: bytes, content_type: str) -> dict[str, Any]:
        if not self.enabled:
            raise EvidenceStorageError("MinIO evidence storage is not configured")
        digest = hashlib.sha256(content).hexdigest()
        event_digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        extension = CONTENT_EXTENSIONS.get(content_type.lower(), "bin")
        object_key = f"{self.prefix}/{event_digest[:2]}/{event_digest}.{extension}"
        try:
            self._client.put_object(
                self.bucket,
                object_key,
                BytesIO(content),
                len(content),
                content_type=content_type,
                metadata={"event-id-sha256": event_digest, "content-sha256": digest},
            )
        except Exception as exc:
            raise EvidenceStorageError("failed to upload alert evidence to MinIO") from exc
        return {
            "snapshotUri": f"/aiyoloapi/alerts/{quote(event_id, safe='')}/evidence",
            "objectStorage": {
                "provider": "minio",
                "bucket": self.bucket,
                "objectKey": object_key,
                "contentType": content_type,
                "sizeBytes": len(content),
                "sha256": digest,
            },
        }

    def read(self, evidence: Mapping[str, Any]) -> EvidenceBody:
        reference = evidence.get("objectStorage") or {}
        if reference.get("provider") != "minio":
            raise EvidenceStorageError("alert evidence is not stored in MinIO")
        bucket = str(reference.get("bucket") or "")
        object_key = str(reference.get("objectKey") or "")
        if bucket != self.bucket or not object_key.startswith(f"{self.prefix}/"):
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
