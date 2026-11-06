"""Issue direct MinIO URLs pinned to the previously verified object version."""
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from minio import Minio

from .minio_store import ApkMinioStore


class MinioTickets:
    def __init__(self, store, signing_client=None):
        self.store = store
        self.signing_client = signing_client or store.client

    def __call__(self, source, artifact, issued_at, expires_at):
        if (source.bucket != self.store.bucket or not source.object_version_id
                or source.object_version_id == "null"):
            raise ValueError("unbound APK object")
        stat = self.store.client.stat_object(source.bucket, source.object_key, version_id=source.object_version_id)
        if stat.size != artifact.size_bytes or stat.etag != source.object_etag:
            raise ValueError("APK object changed")
        # Extra minute accommodates clock/SDK serialization precision. The
        # app's authorization remains the shorter signed interval.
        duration = expires_at - issued_at + timedelta(seconds=60)
        url = self.signing_client.presigned_get_object(source.bucket, source.object_key,
            version_id=source.object_version_id, expires=duration, request_date=issued_at)
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in source.allowed_hosts
                or parsed.username or parsed.password or parsed.fragment
                or parse_qs(parsed.query).get("versionId") != [source.object_version_id]):
            raise ValueError("APK download endpoint must be approved HTTPS with versionId")
        return url, issued_at + duration


def configured_tickets(settings):
    # Deferred: external-only deployments never need MinIO credentials.
    def issue(source, artifact, issued_at, expires_at):
        store = ApkMinioStore.from_settings(settings)
        client = None
        if settings.app_apk_download_endpoint:
            endpoint = urlsplit(settings.app_apk_download_endpoint)
            if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password
                    or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment
                    or endpoint.port not in (None, 443) or not settings.minio_region):
                raise ValueError("invalid public S3 download endpoint")
            client = Minio(endpoint.netloc, access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key, secure=True, region=settings.minio_region)
        return MinioTickets(store, client)(source, artifact, issued_at, expires_at)
    return issue
