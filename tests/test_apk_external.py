"""External transport boundaries, durable jobs and authenticated registration."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from email.message import Message
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

from app import auth
from app.app_updates.contract import ExternalArtifactRequest, SourceRequest
from app.app_updates.external_api import create_external_router
from app.app_updates.external_fetch import ExternalFetcher, FetchError, public_address
from app.app_updates.external_jobs import ExternalJobs
from app.app_updates.models import AppArtifact, AppArtifactSource, AppIdentity, AppUpload
from app.app_updates.uploads import now
from app.database import AccountRecord, AccountSessionRecord, Base, DatabaseManager
from postgresql_support import isolated_postgresql_url
import test_apk_uploads as upload_tests

ROOT = Path(__file__).resolve().parents[1]
RAW = b"PK\x03\x04signed-apk-test"


class Response(io.BytesIO):
    def isclosed(self):
        return self.closed
    def __init__(self, raw=RAW, status=200, **headers):
        super().__init__(raw)
        self.status = status
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key.replace("_", "-")] = str(value)

    def getheader(self, key, default=None):
        return self.headers.get(key, default)


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.connections = []

    def __call__(self, host, ip, timeout):
        owner = self
        response = self.responses.pop(0)
        class Connection:
            sock = None
            closed = False
            def request(self, method, path, headers):
                owner.calls.append((host, ip, method, path, headers))
            def getresponse(self):
                return response
            def close(self):
                self.closed = True
                response.close()
        connection = Connection()
        self.connections.append(connection)
        return connection


def fetcher(responses, **kwargs):
    transport = Transport(responses)
    return ExternalFetcher(resolver=lambda *_: ("8.8.8.8",), connection=transport, **kwargs), transport


def request(key="test", url="https://apk.example.com/file.apk", **extra):
    cls = SourceRequest if extra else ExternalArtifactRequest
    return cls(packageName=upload_tests.PACKAGE, downloadUrl=url,
        allowedDownloadHosts=["apk.example.com"], idempotencyKey=key, reason="test external registration", **extra)


class FetchTests(unittest.TestCase):
    def test_full_stream_no_credentials_and_range_optional(self):
        fetch, transport = fetcher([Response(Content_Length=len(RAW))])
        output = io.BytesIO()
        result = fetch.fetch("https://apk.example.com/file.apk", ["apk.example.com"], output)
        self.assertEqual(RAW, output.getvalue())
        self.assertFalse(result.range_supported)
        self.assertEqual(hashlib.sha256(RAW).hexdigest(), result.sha256)
        self.assertEqual("8.8.8.8", transport.calls[0][1])
        headers = transport.calls[0][4]
        self.assertFalse(set(k.lower() for k in headers) & {"authorization", "cookie", "proxy-authorization", "range"})
        self.assertTrue(transport.connections[0].closed)

    def test_each_redirect_revalidates_dns_hosts_and_https(self):
        for location in ("http://apk.example.com/file", "https://evil.example.com/file", "https://user:secret@apk.example.com/file"):
            with self.subTest(location=location):
                fetch, transport = fetcher([Response(status=302, Location=location)])
                with self.assertRaises(FetchError):
                    fetch.fetch("https://apk.example.com/file", ["apk.example.com"], io.BytesIO())
                self.assertEqual(1, len(transport.calls))
        fetch, transport = fetcher([Response(status=302, Location="/new"), Response()])
        addresses = iter([("8.8.8.8",), ("127.0.0.1",)])
        fetch.resolver = lambda *_: next(addresses)
        with self.assertRaisesRegex(FetchError, "external_address_forbidden"):
            fetch.fetch("https://apk.example.com/file", ["apk.example.com"], io.BytesIO())
        self.assertEqual(1, len(transport.calls))

    def test_nonpublic_ip_dns_mixed_answers_and_bad_urls_rejected(self):
        for value in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:8.8.8.8", "224.0.0.1", "100.64.0.1"):
            self.assertFalse(public_address(value), value)
        fetch, transport = fetcher([])
        fetch.resolver = lambda *_: ("8.8.8.8", "10.0.0.1")
        with self.assertRaisesRegex(FetchError, "external_address_forbidden"):
            fetch.fetch("https://apk.example.com/file", ["apk.example.com"], io.BytesIO())
        for url in ("https://apk.example.com:8443/file", "https://apk.example.com./file", "https://apk.example.com/a\r\nx: y", "https://apk.example.com\\@evil.com"):
            with self.assertRaises(FetchError):
                fetch.fetch(url, ["apk.example.com"], io.BytesIO())
        self.assertEqual([], transport.calls)

    def test_status_html_truncated_over_limit_encoding_and_timeout(self):
        for response, code in [(Response(status=n), "external_http_" + str(n)) for n in (403, 404, 429, 500, 503)] + [
            (Response(b"<html>error", Content_Type="text/html"), "external_not_apk"),
            (Response(b"<html>error"), "external_not_apk"),
            (Response(Content_Length=999), "external_truncated"),
            (Response(Content_Encoding="gzip"), "external_encoding_unsupported")]:
            fetch, _ = fetcher([response])
            with self.assertRaisesRegex(FetchError, code):
                fetch.fetch("https://apk.example.com/f", ["apk.example.com"], io.BytesIO())
        fetch, _ = fetcher([Response()], max_bytes=4)
        with self.assertRaisesRegex(FetchError, "external_too_large"):
            fetch.fetch("https://apk.example.com/f", ["apk.example.com"], io.BytesIO())
        fetch, _ = fetcher([])
        fetch.resolver = lambda *_: (_ for _ in ()).throw(TimeoutError())
        with self.assertRaisesRegex(FetchError, "external_timeout"):
            fetch.fetch("https://apk.example.com/f", ["apk.example.com"], io.BytesIO())

    def test_tls_connect_uses_checked_ip_with_dns_sni(self):
        from app.app_updates.external_fetch import PinnedHTTPS
        context = unittest.mock.Mock()
        raw = unittest.mock.Mock()
        connection = PinnedHTTPS("apk.example.com", "8.8.8.8", 3, context=context)
        with patch("socket.create_connection", return_value=raw) as connect:
            connection.connect()
        connect.assert_called_once_with(("8.8.8.8", 443), 3)
        context.wrap_socket.assert_called_once_with(raw, server_hostname="apk.example.com")
        connection.close()


class JobAssertions:
    def records(self, responses=None):
        self.actor = str(uuid4())
        with self.db.session() as session:
            session.add(AccountRecord(account_id=self.actor, username="admin", password_hash="fixture",
                role="admin", platform_role="PLATFORM_ADMIN"))
            session.add(AppIdentity(package_name=upload_tests.PACKAGE, publisher_id="test", approved_signer_sha256="b" * 64))
        fetch, self.transport = fetcher(responses or [Response()])
        self.service = ExternalJobs(self.db, upload_tests.Verifier(), fetch, root=self.root / "external",
            compatibility=upload_tests.COMPAT)

    def test_success_duplicate_and_same_bytes_add_source(self):
        self.records([Response(), Response()])
        first = self.service.register(self.actor, request())
        self.assertEqual(first, self.service.register(self.actor, request()))
        self.service.process_one()
        with self.db.session() as session:
            source = session.scalar(select(AppArtifactSource))
            artifact_id, digest = source.artifact_id, source.verified_sha256
            self.assertEqual("external", source.storage_mode)
            self.assertIsNone(source.bucket)
            job = session.scalar(select(AppUpload))
            self.assertFalse(job.fetch_evidence["rangeAdvertised"])
        self.service.register(self.actor, request("source", "https://apk.example.com/mirror.apk", expectedArtifactSha256=digest),
            target_artifact_id=artifact_id)
        self.service.process_one()
        with self.db.session() as session:
            sources = session.scalars(select(AppArtifactSource).order_by(AppArtifactSource.source_revision)).all()
            self.assertEqual([1, 2], [v.source_revision for v in sources])
        self.assertEqual([], list(self.service.root.glob("*.apk")))

    def test_revoked_role_failure_and_idempotency_conflict(self):
        self.records()
        self.service.register(self.actor, request())
        with self.assertRaisesRegex(Exception, "idempotency_conflict"):
            self.service.register(self.actor, request(url="https://apk.example.com/changed"))
        with self.db.session() as session:
            session.get(AccountRecord, self.actor).enabled = False
        self.service.process_one()
        with self.db.session() as session:
            self.assertEqual("platform_admin_required", session.scalar(select(AppUpload)).error_code)
            self.assertIsNone(session.scalar(select(AppArtifactSource)))
        self.assertEqual([], self.transport.calls)

    def test_restart_fencing_and_cleanup_failure_recovery(self):
        self.records([Response(), Response()])
        self.service.register(self.actor, request())
        def expired():
            with self.db.session() as session:
                session.scalar(select(AppUpload)).lease_until = now() - timedelta(seconds=1)
            self.service.recover()
        self.service.verifier = upload_tests.Verifier(expired)
        self.service.process_one()
        with self.db.session() as session:
            self.assertEqual(0, session.get(AppIdentity, upload_tests.PACKAGE).version_high_water)
            self.assertEqual("retryable", session.scalar(select(AppUpload)).state)
        self.service.verifier = upload_tests.Verifier()
        with patch.object(Path, "unlink", side_effect=PermissionError()):
            self.service.process_one()
        with self.db.session() as session:
            self.assertTrue(session.scalar(select(AppUpload)).cleanup_pending)
            self.assertEqual("succeeded", session.scalar(select(AppUpload)).state)
        self.service.recover()
        self.assertEqual([], list(self.service.root.glob("*.apk")))

    def test_file_replaced_against_known_target_is_rejected(self):
        self.records([Response(), Response(RAW + b"changed")])
        self.service.register(self.actor, request())
        self.service.process_one()
        with self.db.session() as session:
            source = session.scalar(select(AppArtifactSource))
            artifact, digest = source.artifact_id, source.verified_sha256
        self.service.register(self.actor, request("changed", "https://apk.example.com/mirror", expectedArtifactSha256=digest),
            target_artifact_id=artifact)
        self.service.process_one()
        with self.db.session() as session:
            job = session.scalar(select(AppUpload).where(AppUpload.idempotency_key == "changed"))
            self.assertEqual("external_file_changed", job.error_code)
            self.assertEqual(1, len(session.scalars(select(AppArtifactSource)).all()))

    def test_expired_download_files_and_external_history_are_preserved_safely(self):
        self.records()
        self.service.register(self.actor, request())
        self.service.root.mkdir(parents=True)
        with self.db.session() as session:
            job = session.scalar(select(AppUpload))
            job.state, job.lease_token = "processing", str(uuid4())
            job.lease_until = now() - timedelta(seconds=1)
            abandoned = self.service.root / (job.upload_id + "-" + job.lease_token + ".apk")
        abandoned.write_bytes(b"partial")
        self.service.recover()
        self.assertFalse(abandoned.exists())
        self.service.process_one()
        with self.db.session() as session:
            self.assertEqual("succeeded", session.scalar(select(AppUpload)).state)

    def test_upload_worker_does_not_claim_external_and_capacity_is_shared(self):
        self.records()
        self.service.max_jobs = 1
        self.service.register(self.actor, request())
        uploads = upload_tests.ApkUploads(self.db, upload_tests.Verifier(), upload_tests.Store(),
            root=self.root / "uploads", compatibility=upload_tests.COMPAT, max_jobs=1)
        self.assertFalse(uploads.process_one())
        with self.assertRaisesRegex(Exception, "apk_upload_capacity"):
            uploads.begin(self.actor)

    def test_migration_refuses_external_history_downgrade(self):
        from alembic import command
        from test_app_update_storage import migration_config
        # The PostgreSQL fixture was migrated through the CLI. SQLite lifecycle
        # cases intentionally use create_all and have no Alembic version row.
        if self.db.backend != "postgresql":
            return
        self.records()
        self.service.register(self.actor, request())
        with self.assertRaisesRegex(RuntimeError, "durable history"):
            command.downgrade(migration_config(self.db.url), "20261029_28")


class SQLiteExternalTests(JobAssertions, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="apk-external-", dir=ROOT / ".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = DatabaseManager("sqlite+pysqlite:///" + (self.root / "test.db").as_posix())
        Base.metadata.create_all(self.db.engine)
        self.addCleanup(self.db.close)

    def test_http_auth_json_size_and_sensitive_validation_errors(self):
        self.records()
        token = "test-external-account-session-token"
        with self.db.session() as session:
            session.add(AccountSessionRecord(session_hash=auth._session_hash(token), account_id=self.actor,
                username="admin", role="admin", expires_at=now() + timedelta(hours=1)))
        app = FastAPI()
        app.include_router(create_external_router(lambda: self.service))
        client = TestClient(app)
        path = "/aiyoloapi/admin/app-updates/external-artifacts"
        with patch("app.auth.database", self.db), patch.object(auth.settings, "deployment_env", "production"):
            self.assertEqual(401, client.post(path, content=b"unused").status_code)
            headers = {"Authorization": "Bearer " + token}
            response = client.post(path, headers=headers, json=request().model_dump())
            self.assertEqual(202, response.status_code, response.text)
            bad = request().model_dump() | {"downloadUrl": "https://user:secret@apk.example.com/file"}
            response = client.post(path, headers=headers, json=bad)
            self.assertEqual(422, response.status_code)
            self.assertNotIn("secret", response.text)
            self.assertEqual(413, client.post(path, headers=headers | {"content-type": "application/json"}, content=b"x" * 16385).status_code)
            with self.db.session() as session:
                session.get(AccountRecord, self.actor).platform_role = "NORMAL_USER"
            self.assertEqual(403, client.post(path, headers=headers, json=request().model_dump()).status_code)


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL")
class PostgreSQLExternalTests(JobAssertions, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="apk-external-pg-", dir=ROOT / ".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cluster = isolated_postgresql_url("apk_external")
        url = cluster.__enter__()
        self.addCleanup(lambda: cluster.__exit__(None, None, None))
        self.db = DatabaseManager(url)
        self.addCleanup(self.db.close)

    def test_concurrent_register_and_claim_are_idempotent(self):
        self.records()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.service.register(self.actor, request()), range(2)))
        self.assertEqual(results[0], results[1])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.service.process_one(), range(2)))
        self.assertEqual([False, True], sorted(results))
        self.assertEqual(1, len(self.transport.calls))
