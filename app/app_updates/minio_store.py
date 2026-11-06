"""Version-pinned APK objects; business APIs never proxy their download bytes."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error
from minio.versioningconfig import ENABLED
import urllib3


class StorageError(Exception):
    def __init__(self, code="apk_storage_unavailable"):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    version_id: str
    etag: str


class ApkMinioStore:
    def __init__(self, client, *, bucket, prefix="app-apks", allowed_hosts=()):
        self.client, self.bucket = client, bucket
        self.prefix = prefix.strip("/")
        self.allowed_hosts = tuple(allowed_hosts)
        if not bucket or not self.prefix or ".." in self.prefix.split("/"):
            raise ValueError("invalid APK object namespace")

    @classmethod
    def from_settings(cls, settings):
        if not all((settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key)):
            raise StorageError("apk_storage_not_configured")
        parsed = urlsplit(settings.minio_endpoint if "://" in settings.minio_endpoint else "//" + settings.minio_endpoint)
        if (not parsed.netloc or parsed.path not in ("", "/") or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.scheme not in ("", "http", "https")):
            raise StorageError("apk_storage_not_configured")
        client = Minio(parsed.netloc, access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key, secure=parsed.scheme == "https" if parsed.scheme else settings.minio_secure,
            region=settings.minio_region or None,
            http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=5, read=60), retries=False))
        return cls(client, bucket=settings.app_apk_bucket, prefix=settings.app_apk_object_prefix,
                   allowed_hosts=[v.strip() for v in settings.app_apk_allowed_hosts.split(",") if v.strip()])

    def promote(self, path: Path, *, artifact_id, sha256, size_bytes):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", artifact_id) or not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise StorageError("invalid_object_identity")
        # Refuse nonversioned buckets: every published source must remain pinned
        # to the exact object version even if an operator later reuses a key.
        try:
            if not self.client.bucket_exists(self.bucket):
                raise StorageError("apk_bucket_missing")
            if self.client.get_bucket_versioning(self.bucket).status != ENABLED:
                raise StorageError("apk_bucket_versioning_required")
            key = f"{self.prefix}/{artifact_id}/{sha256}.apk"
            try:
                current = self.client.stat_object(self.bucket, key)
            except S3Error as exc:
                if exc.code not in ("NoSuchKey", "NoSuchObject", "NotFound"):
                    raise
                current = None
            if current is not None:
                stored = StoredObject(self.bucket, key, current.version_id, current.etag)
                self.verify(stored, sha256, size_bytes)
                return stored
            # Read the very same staging file again and validate its hash before
            # transfer; then read the stored version back, never trust ETag=hash.
            digest, size = hashlib.sha256(), 0
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    size += len(block)
                    digest.update(block)
            if size != size_bytes or digest.hexdigest() != sha256:
                raise StorageError("apk_staging_changed")
            with path.open("rb") as source:
                result = self.client.put_object(self.bucket, key, source, size_bytes,
                    content_type="application/vnd.android.package-archive", metadata={"sha256": sha256},
                    num_parallel_uploads=1)
            stored = StoredObject(self.bucket, key, result.version_id, result.etag)
            self.verify(stored, sha256, size_bytes)
            return stored
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError() from exc

    def verify(self, stored, sha256, size_bytes):
        if not stored.version_id or stored.version_id == "null":
            raise StorageError("apk_object_version_missing")
        response = None
        try:
            stat = self.client.stat_object(stored.bucket, stored.key, version_id=stored.version_id)
            if stat.size != size_bytes:
                raise StorageError("apk_object_mismatch")
            response = self.client.get_object(stored.bucket, stored.key, version_id=stored.version_id)
            digest, size = hashlib.sha256(), 0
            for block in response.stream(1024 * 1024):
                size += len(block)
                if size > size_bytes:
                    raise StorageError("apk_object_mismatch")
                digest.update(block)
            if size != size_bytes or digest.hexdigest() != sha256:
                raise StorageError("apk_object_mismatch")
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError() from exc
        finally:
            if response:
                response.close()
                response.release_conn()
