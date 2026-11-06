"""Version pinning/readback faults plus real SDK -> MinIO -> DB integration."""
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

from minio.deleteobjects import DeleteObject
from minio.error import S3Error
from minio.versioningconfig import ENABLED, VersioningConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch
from sqlalchemy import select

from app.app_updates.apk_verifier import ApkVerifier
from app.app_updates.minio_store import ApkMinioStore, StorageError
from app.app_updates.models import AppArtifactSource, AppIdentity, AppUpload
from app.app_updates.uploads import ApkUploads, now
from app.app_updates.upload_api import create_upload_router
from app import auth
from app.database import AccountSessionRecord
from app.config import settings
from apk_test_support import ApkFixtures
import test_apk_uploads as upload_tests
from test_apk_uploads import COMPAT, PACKAGE

ROOT = Path(__file__).resolve().parents[1]


class Response(io.BytesIO):
    def stream(self, size):
        while block := self.read(size):
            yield block

    def release_conn(self):
        pass


class Client:
    def __init__(self):
        self.data, self.versioned, self.error, self.corrupt = None, True, None, False
        self.puts = 0

    def bucket_exists(self, bucket):
        return True

    def get_bucket_versioning(self, bucket):
        return SimpleNamespace(status=ENABLED if self.versioned else "Suspended")

    def stat_object(self, bucket, key, **kwargs):
        if self.data is None:
            raise S3Error(None, "NoSuchKey", "missing", "", "", "")
        return SimpleNamespace(size=len(self.data), version_id="v1", etag="etag")

    def put_object(self, bucket, key, stream, length, **kwargs):
        if self.error:
            raise S3Error(None, self.error, "do not expose", "", "", "")
        self.data = stream.read()
        self.puts += 1
        return SimpleNamespace(version_id="v1", etag="etag")

    def get_object(self, bucket, key, **kwargs):
        return Response(b"corrupt" if self.corrupt else self.data)


class MinioStoreTests(unittest.TestCase):
    def test_versioning_retry_digest_and_secret_safe_errors(self):
        with tempfile.TemporaryDirectory(prefix="apk-store-", dir=ROOT / ".tmp") as folder:
            path = Path(folder) / "input.apk"
            path.write_bytes(b"apk-one")
            client = Client()
            store = ApkMinioStore(client, bucket="test-bucket")
            args = dict(artifact_id=uuid4().hex, sha256=hashlib.sha256(b"apk-one").hexdigest(), size_bytes=7)
            client.versioned = False
            with self.assertRaisesRegex(StorageError, "versioning_required"):
                store.promote(path, **args)
            client.versioned = True
            for failure in ("AccessDenied", "QuotaExceeded", "XMinioStorageFull"):
                client.error = failure
                with self.assertRaisesRegex(StorageError, "^apk_storage_unavailable$"):
                    store.promote(path, **args)
            client.error = None
            first = store.promote(path, **args)
            self.assertEqual(first, store.promote(path, **args))
            self.assertEqual(1, client.puts)
            client.corrupt = True
            with self.assertRaisesRegex(StorageError, "apk_object_mismatch"):
                store.promote(path, **args)


@unittest.skipUnless(os.environ.get("RUN_APK_MINIO_TESTS") == "1", "requires real MinIO and SDK")
class RealMinioIntegration(upload_tests.PostgreSQLUploadTests):
    # Reuse isolated PostgreSQL setup only; inherited lifecycle cases are covered
    # in test_apk_uploads, so do not run them again here.
    test_capacity_expired_receive_and_revoked_admin = None
    test_concurrent_claim_executes_only_once = None
    test_expired_old_worker_is_fenced_before_verification_commit = None
    test_idempotency_conflict_and_same_filename_different_bytes = None
    test_storage_failure_retry_and_cleanup_recovery = None
    test_success_immutable_source_and_duplicate = None

    def test_real_signed_upload_recovery_version_pinning_and_readback(self):
        self.records()
        fixtures = ApkFixtures(self.root)
        apk = fixtures.apk("real-minio", native_abi="arm64-v8a")
        signer = fixtures.signer(apk)
        with self.db.session() as session:
            session.get(AppIdentity, PACKAGE).approved_signer_sha256 = signer
        template = ApkMinioStore.from_settings(settings)
        client = template.client
        bucket = "apk-test-" + uuid4().hex
        client.make_bucket(bucket)
        evidence = {"bucket": bucket}
        try:
            store = ApkMinioStore(client, bucket=bucket, allowed_hosts=("test.example.com",))
            self.service = ApkUploads(self.db, ApkVerifier(fixtures.tools), store,
                root=self.root / "uploads", compatibility=COMPAT)
            raw = apk.read_bytes()
            token = "real-apk-upload-test-session-token"
            with self.db.session() as session:
                session.add(AccountSessionRecord(session_hash=auth._session_hash(token), account_id=self.actor,
                    username="admin", role="admin", expires_at=now() + timedelta(hours=1)))
            app = FastAPI()
            app.include_router(create_upload_router(lambda: self.service, max_bytes=8 * 1024**3, receive_seconds=300))
            with patch("app.auth.database", self.db):
                response = TestClient(app).post("/aiyoloapi/admin/app-updates/artifacts/upload",
                    headers={"Authorization": "Bearer " + token},
                    files={"apk": ("candidate.apk", raw)}, data={"idempotencyKey": "real-minio", "reason": "real acceptance"})
            self.assertEqual(202, response.status_code, response.text)
            with self.db.session() as session:
                identity = session.scalar(select(AppUpload.upload_id))
            evidence["authenticatedStreamingHttp202"] = True
            # A real unversioned bucket must never produce a usable source.
            self.service.process_one()
            with self.db.session() as session:
                job = session.get(AppUpload, identity)
                self.assertEqual("retryable", job.state)
                self.assertEqual("apk_bucket_versioning_required", job.error_code)
                self.assertIsNone(session.scalar(select(AppArtifactSource)))
                job.lease_until = now() - timedelta(seconds=1)
            client.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
            evidence["realVersioningFailureRecovered"] = True
            # Resume verified file, upload and full object readback.
            self.service.process_one()
            self.assertEqual("verified", self.service.status(identity)["state"])
            with self.db.session() as session:
                source = session.scalar(select(AppArtifactSource))
                key, version = source.object_key, source.object_version_id
                evidence.update(sha256=source.verified_sha256, sizeBytes=source.verified_size_bytes,
                    versionId=version, etag=source.object_etag, signerSha256=signer,
                    verificationEvidence=source.verification_evidence_ref)
            # Even an operator's later put at the same key cannot replace the
            # version recorded by our source. Never delete or touch business keys.
            client.put_object(bucket, key, io.BytesIO(b"changed"), 7)
            response = client.get_object(bucket, key, version_id=version)
            try:
                self.assertEqual(raw, response.read())
            finally:
                response.close()
                response.release_conn()
            evidence["pinnedVersionUnaffectedByLaterPut"] = True
            # Restore latest only within this test bucket, then verify duplicate
            # file uses the same artifact and a recorded verified source version.
            client.put_object(bucket, key, io.BytesIO(raw), len(raw))
            duplicate, _ = self.enqueue(raw)
            self.service.process_one()
            self.assertEqual(self.service.status(identity), self.service.status(duplicate))
            evidence["duplicateArtifactReused"] = True
        finally:
            errors = list(client.remove_objects(bucket, (DeleteObject(obj.object_name, obj.version_id)
                for obj in client.list_objects(bucket, recursive=True, include_version=True))))
            self.assertEqual([], errors)
            client.remove_bucket(bucket)
            evidence["testBucketRemoved"] = True
            evidence_root = Path(os.environ["APK_TEST_EVIDENCE_ROOT"])
            evidence_root.mkdir(parents=True, exist_ok=True)
            (evidence_root / "minio-integration.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
