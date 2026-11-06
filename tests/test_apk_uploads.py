"""Upload lifecycle, authentication, bounded parsing and storage failures."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.requests import Request

from app import auth
from app.app_updates.apk_verifier import VerifiedApk
from app.app_updates.minio_store import StorageError, StoredObject
from app.app_updates.models import AppArtifact, AppArtifactSource, AppIdentity, AppUpload
from app.app_updates.upload_api import create_upload_router
from app.app_updates.uploads import ApkUploads, UploadError, now
from app.app_updates.verification_jobs import BuildCompatibility
from app.database import AccountRecord, AccountSessionRecord, Base, DatabaseManager
from postgresql_support import isolated_postgresql_url

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "com.aiyolo.inspection"
COMPAT = BuildCompatibility(1, 1, 19, 18, 19, "ci/test/build.json")


class Verifier:
    def __init__(self, hook=None):
        self.hook = hook

    def verify(self, stream, **kwargs):
        data = stream.read()
        if self.hook:
            self.hook()
        return VerifiedApk(PACKAGE, 1, "test", 27, ("arm64-v8a",), len(data),
            hashlib.sha256(data).hexdigest(), "b" * 64, "evidence/test/report.json")


class Store:
    allowed_hosts = ("apk.example.com",)

    def __init__(self):
        self.failure = None
        self.calls = 0

    def promote(self, path, *, artifact_id, sha256, size_bytes):
        self.calls += 1
        if self.failure:
            raise StorageError(self.failure)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha256
        return StoredObject("test-apks", f"apks/{artifact_id}/{sha256}.apk", "version-1", "etag-1")


class UploadAssertions:
    def records(self):
        self.actor = str(uuid4())
        with self.db.session() as session:
            session.add(AccountRecord(account_id=self.actor, username="admin", password_hash="fixture",
                role="admin", platform_role="PLATFORM_ADMIN"))
            session.add(AppIdentity(package_name=PACKAGE, publisher_id="test", approved_signer_sha256="b" * 64))
        self.store = Store()
        self.service = ApkUploads(self.db, Verifier(), self.store, root=self.root / "uploads", compatibility=COMPAT)

    def enqueue(self, data=b"apk-one", key=None):
        identity = self.service.begin(self.actor)
        self.service.path(identity).write_bytes(data)
        result = self.service.finish(identity, idempotency_key=key or uuid4().hex, reason="test upload",
            size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        return identity, result

    def test_success_immutable_source_and_duplicate(self):
        self.records()
        first, _ = self.enqueue(key="same")
        self.assertTrue(self.service.process_one())
        self.assertFalse(self.service.path(first).exists())
        duplicate, result = self.enqueue(key="same")
        self.assertEqual("verified", result["state"])
        self.assertFalse(self.service.path(duplicate).exists())
        second, _ = self.enqueue()
        self.service.process_one()
        self.assertEqual(self.service.status(first), self.service.status(second))
        with self.db.session() as session:
            sources = session.scalars(select(AppArtifactSource)).all()
            self.assertEqual(1, len(sources))
            self.assertEqual("version-1", sources[0].object_version_id)
            self.assertEqual("etag-1", sources[0].object_etag)

    def test_idempotency_conflict_and_same_filename_different_bytes(self):
        self.records()
        first, _ = self.enqueue(key="same")
        identity = self.service.begin(self.actor)
        self.service.path(identity).write_bytes(b"different")
        with self.assertRaisesRegex(UploadError, "idempotency_conflict"):
            self.service.finish(identity, idempotency_key="same", reason="test upload", size_bytes=9,
                sha256=hashlib.sha256(b"different").hexdigest())
        self.service.fail_receive(identity, "idempotency_conflict")
        self.service.process_one()
        different, _ = self.enqueue(b"different")
        self.service.process_one()
        self.assertEqual("failed", self.service.status(different)["state"])
        self.assertEqual("verified", self.service.status(first)["state"])

    def test_storage_failure_retry_and_cleanup_recovery(self):
        self.records()
        identity, _ = self.enqueue()
        self.store.failure = "apk_storage_unavailable"
        self.service.process_one()
        with self.db.session() as session:
            job = session.get(AppUpload, identity)
            self.assertEqual("retryable", job.state)
            self.assertIsNotNone(job.resolved_artifact_id)
            job.lease_until = now() - timedelta(seconds=1)
        self.assertTrue(self.service.path(identity).exists())
        self.store.failure = None
        original = Path.unlink
        def denied(path, *args, **kwargs):
            if path == self.service.path(identity):
                raise PermissionError()
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", denied):
            self.service.process_one()
        with self.db.session() as session:
            self.assertTrue(session.get(AppUpload, identity).cleanup_pending)
        restarted = ApkUploads(self.db, Verifier(), self.store, root=self.service.root, compatibility=COMPAT)
        restarted.recover()
        self.assertFalse(self.service.path(identity).exists())
        self.assertEqual("verified", self.service.status(identity)["state"])

    def test_capacity_expired_receive_and_revoked_admin(self):
        self.records()
        self.service.max_jobs = 1
        identity = self.service.begin(self.actor)
        with self.assertRaisesRegex(UploadError, "apk_upload_capacity"):
            self.service.begin(self.actor)
        with self.db.session() as session:
            session.get(AppUpload, identity).lease_until = now() - timedelta(seconds=1)
        self.service.recover()
        self.assertEqual("failed", self.service.status(identity)["state"])
        identity, _ = self.enqueue()
        with self.db.session() as session:
            session.get(AccountRecord, self.actor).platform_role = "NORMAL_USER"
        self.service.process_one()
        self.assertEqual("failed", self.service.status(identity)["state"])
        self.assertEqual(0, self.store.calls)

    def test_expired_old_worker_is_fenced_before_verification_commit(self):
        self.records()
        identity, _ = self.enqueue()
        def lose_lease():
            with self.db.session() as session:
                session.get(AppUpload, identity).lease_until = now() - timedelta(seconds=1)
            self.service.recover()
        self.service.verifier = Verifier(lose_lease)
        self.service.process_one()
        with self.db.session() as session:
            self.assertEqual(0, session.get(AppIdentity, PACKAGE).version_high_water)
            self.assertEqual("retryable", session.get(AppUpload, identity).state)
        self.assertTrue(self.service.path(identity).exists())
        self.service.verifier = Verifier()
        self.service.process_one()
        self.assertEqual("verified", self.service.status(identity)["state"])


class SQLiteUploadTests(UploadAssertions, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="apk-uploads-", dir=ROOT / ".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = DatabaseManager("sqlite+pysqlite:///" + (self.root / "test.db").as_posix())
        Base.metadata.create_all(self.db.engine)
        self.addCleanup(self.db.close)

    def api(self, max_bytes=32, receive_seconds=30):
        self.records()
        token = "upload-test-session-token-with-sufficient-length"
        with self.db.session() as session:
            session.add(AccountSessionRecord(session_hash=auth._session_hash(token), account_id=self.actor,
                username="admin", role="admin", expires_at=now() + timedelta(hours=1)))
        self.enterContext(patch("app.auth.database", self.db))
        self.enterContext(patch.object(auth.settings, "deployment_env", "production"))
        app = FastAPI()
        self.router = create_upload_router(lambda: self.service, max_bytes=max_bytes, receive_seconds=receive_seconds)
        app.include_router(self.router)
        self.app, self.client = app, TestClient(app)
        self.headers = {"Authorization": "Bearer " + token}

    def post(self, data=b"apk-one", **kwargs):
        return self.client.post("/aiyoloapi/admin/app-updates/artifacts/upload", headers=self.headers,
            files={"apk": ("../../outside.apk", data)}, data={"idempotencyKey": "test", "reason": "test upload"}, **kwargs)

    def test_api_authentication_current_role_and_ignored_filename(self):
        self.api()
        self.assertEqual(401, self.client.post("/aiyoloapi/admin/app-updates/artifacts/upload", content=b"bad").status_code)
        response = self.post()
        self.assertEqual(202, response.status_code, response.text)
        self.assertNotIn(str(self.root), response.text)
        self.assertEqual(1, len(list(self.service.root.glob("*.apk"))))
        with self.db.session() as session:
            session.get(AccountRecord, self.actor).platform_role = "NORMAL_USER"
        self.assertEqual(403, self.post().status_code)
        with self.db.session() as session:
            session.get(AccountRecord, self.actor).enabled = False
        self.assertEqual(401, self.post().status_code)

    def test_api_limits_malformed_duplicate_parts_and_disconnect(self):
        self.api(max_bytes=5)
        self.assertEqual(413, self.post().status_code)
        response = self.client.post("/aiyoloapi/admin/app-updates/artifacts/upload", headers=self.headers,
            files=[("apk", ("same.apk", b"123")), ("apk", ("same.apk", b"123"))],
            data={"idempotencyKey": "key", "reason": "test"})
        self.assertEqual(422, response.status_code)
        response = self.client.post("/aiyoloapi/admin/app-updates/artifacts/upload",
            headers=self.headers | {"content-type": "multipart/form-data; boundary=x"}, content=b"--x\r\n")
        self.assertEqual(422, response.status_code)
        self.assertEqual([], list(self.service.root.glob("*.apk")))

    def test_api_total_receive_timeout(self):
        self.api(receive_seconds=0.01)
        endpoint = self.router.routes[0].endpoint
        async def slow_receive():
            await asyncio.sleep(0.1)
            return {"type": "http.request", "body": b"", "more_body": False}
        request = Request({"type": "http", "headers": [(b"authorization", self.headers["Authorization"].encode()),
            (b"content-type", b"multipart/form-data; boundary=x")]}, slow_receive)
        with self.assertRaises(Exception) as caught:
            asyncio.run(endpoint(request))
        self.assertEqual(408, caught.exception.status_code)
        self.assertEqual([], list(self.service.root.glob("*.apk")))

    def test_api_unauthorized_body_not_consumed_and_legacy_rejected(self):
        self.api()
        endpoint = self.router.routes[0].endpoint
        async def unexpected_receive():
            self.fail("unauthorized request body was consumed")
        request = Request({"type": "http", "headers": [(b"content-type", b"multipart/form-data; boundary=x")]},
            unexpected_receive)
        with self.assertRaises(Exception) as caught:
            asyncio.run(endpoint(request))
        self.assertEqual(401, caught.exception.status_code)
        with patch.object(auth.settings, "deployment_env", "development"), patch.object(auth.settings, "admin_token", "legacy-test"):
            response = self.client.post("/aiyoloapi/admin/app-updates/artifacts/upload",
                headers={"x-admin-token": "legacy-test"}, content=b"unused")
        self.assertEqual(403, response.status_code)

    def test_api_disconnected_stream_fails_and_cleans(self):
        self.api()
        async def disconnected():
            return {"type": "http.disconnect"}
        request = Request({"type": "http", "headers": [(b"authorization", self.headers["Authorization"].encode()),
            (b"content-type", b"multipart/form-data; boundary=x")]}, disconnected)
        with self.assertRaises(Exception) as caught:
            asyncio.run(self.router.routes[0].endpoint(request))
        self.assertEqual(422, caught.exception.status_code)
        self.assertEqual([], list(self.service.root.glob("*.apk")))


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL")
class PostgreSQLUploadTests(UploadAssertions, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="apk-upload-pg-", dir=ROOT / ".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cluster = isolated_postgresql_url("apk_upload")
        url = cluster.__enter__()
        self.addCleanup(lambda: cluster.__exit__(None, None, None))
        self.db = DatabaseManager(url)
        self.addCleanup(self.db.close)

    def test_concurrent_claim_executes_only_once(self):
        self.records()
        identity, _ = self.enqueue()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.service.process_one(), range(2)))
        self.assertEqual([False, True], sorted(results))
        self.assertEqual(1, self.store.calls)
        self.assertEqual("verified", self.service.status(identity)["state"])
