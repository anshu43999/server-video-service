"""Real TLS HTTP, real APK signing/verifying, real isolated PostgreSQL.

Only the connection factory maps the checked public test IP to a loopback
fixture. Production code has no private-address or TLS-verification bypass.
"""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import io
import os
from pathlib import Path
import ssl
import threading
import time
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app.app_updates.apk_verifier import ApkVerifier
from app.app_updates.external_api import create_external_router
from app.app_updates.external_fetch import ExternalFetcher, FetchError, PinnedHTTPS
from app.app_updates.external_jobs import ExternalJobs
from app.app_updates.models import AppArtifactSource, AppIdentity, AppUpload
from app.app_updates.uploads import now
from app.database import AccountSessionRecord
from apk_test_support import ApkFixtures
import test_apk_external as unit


class Origin:
    def __init__(self, root, raw):
        self.raw, self.requests = raw, []
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "apk.example.com")])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("apk.example.com")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
        cert_path, key_path = root / "origin.crt", root / "origin.key"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        self.context = ssl.create_default_context(cafile=str(cert_path))
        owner = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def do_GET(self):
                owner.requests.append({"path": self.path, "headers": dict(self.headers)})
                if self.path in ("/redirect", "/downgrade"):
                    self.send_response(302)
                    self.send_header("Location", "/file.apk" if self.path == "/redirect" else "http://apk.example.com/file.apk")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = int(self.path[1:]) if self.path in ("/403", "/404", "/429", "/503") else 200
                content = b"<html>not an apk</html>" if self.path == "/html" else owner.raw
                self.send_response(status)
                self.send_header("Content-Length", str(len(content) + (100 if self.path == "/truncated" else 0)))
                self.send_header("Content-Type", "text/html" if self.path == "/html" else "application/octet-stream")
                # Intentionally omit Accept-Ranges: full download remains usable.
                self.send_header("Connection", "close")
                self.end_headers()
                if self.path == "/slow":
                    time.sleep(0.2)
                try:
                    self.wfile.write(content)
                except (OSError, ssl.SSLError):
                    pass
                self.close_connection = True
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def connection(self, host, checked_ip, timeout):
        assert checked_ip == "8.8.8.8" and host == "apk.example.com"
        return PinnedHTTPS(host, "127.0.0.1", timeout, context=self.context, port=self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


@unittest.skipUnless(os.environ.get("RUN_APK_EXTERNAL_TESTS") == "1", "requires real SDK and isolated PostgreSQL")
class ExternalRealTests(unittest.TestCase):
    setUp = unit.PostgreSQLExternalTests.setUp
    records = unit.JobAssertions.records

    def test_tls_api_full_verification_changed_source_and_no_hosted_replica(self):
        self.records()
        fixture = ApkFixtures(self.root)
        apk = fixture.apk("external-fixture", native_abi="arm64-v8a")
        raw = apk.read_bytes()
        with self.db.session() as session:
            session.get(AppIdentity, unit.upload_tests.PACKAGE).approved_signer_sha256 = fixture.signer(apk)
        origin = Origin(self.root, raw)
        self.addCleanup(origin.close)
        fetcher = ExternalFetcher(resolver=lambda *_: ("8.8.8.8",), connection=origin.connection)
        self.service = ExternalJobs(self.db, ApkVerifier(fixture.tools), fetcher,
            root=self.root / "external", compatibility=unit.upload_tests.COMPAT)
        token = "external-real-http-session-test-token"
        with self.db.session() as session:
            session.add(AccountSessionRecord(session_hash=auth._session_hash(token), account_id=self.actor,
                username="admin", role="admin", expires_at=now() + timedelta(hours=1)))
        app = FastAPI()
        app.include_router(create_external_router(lambda: self.service))
        with patch("app.auth.database", self.db):
            response = TestClient(app).post("/aiyoloapi/admin/app-updates/external-artifacts",
                headers={"Authorization": "Bearer " + token, "Cookie": "business=must-not-leak"},
                json=unit.request(url="https://apk.example.com/redirect").model_dump())
        self.assertEqual(202, response.status_code, response.text)
        self.service.process_one()
        with self.db.session() as session:
            job = session.scalar(select(AppUpload))
            self.assertEqual("succeeded", job.state, job.error_code)
            source = session.scalar(select(AppArtifactSource))
            artifact_id, digest = source.artifact_id, source.verified_sha256
            evidence = {"authenticated202": True, "state": job.state, "sizeBytes": source.verified_size_bytes,
                "sha256": digest, "fetchEvidence": job.fetch_evidence, "sdkEvidence": source.verification_evidence_ref,
                "testConnectionMapping": "validated public fixture IP mapped to loopback TLS origin; production unchanged"}
        self.assertEqual([], list(self.service.root.glob("*.apk")))
        for call in origin.requests:
            self.assertFalse({k.lower() for k in call["headers"]} & {"cookie", "authorization", "x-admin-token"})
        # A replacement at the same hosting URL cannot become a second source
        # for the original artifact. No object-storage service is configured.
        origin.raw = raw + b"replacement"
        body = unit.request("changed", "https://apk.example.com/file.apk", expectedArtifactSha256=digest)
        self.service.register(self.actor, body, target_artifact_id=artifact_id)
        self.service.process_one()
        with self.db.session() as session:
            changed = session.scalar(select(AppUpload).where(AppUpload.idempotency_key == "changed"))
            self.assertEqual("external_file_changed", changed.error_code)
            self.assertEqual(1, len(session.scalars(select(AppArtifactSource)).all()))
        self.assertEqual([], list(self.service.root.glob("*.apk")))
        evidence.update(noHostedReplica=True, replacedSourceRejected=True, originRequests=origin.requests)
        directory = Path(os.environ["APK_TEST_EVIDENCE_ROOT"])
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "external-tls-integration.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    def test_tls_status_truncation_deadline_and_certificate_verification(self):
        origin = Origin(self.root, unit.RAW)
        self.addCleanup(origin.close)
        for path, code in [("/" + str(n), "external_http_" + str(n)) for n in (403, 404, 429, 503)] + [
            ("/html", "external_not_apk"), ("/truncated", "external_truncated"), ("/downgrade", "external_url_not_allowed")]:
            with self.subTest(path=path):
                fetcher = ExternalFetcher(resolver=lambda *_: ("8.8.8.8",), connection=origin.connection)
                with self.assertRaisesRegex(FetchError, code):
                    fetcher.fetch("https://apk.example.com" + path, ["apk.example.com"], io.BytesIO())
        fetcher = ExternalFetcher(seconds=0.05, resolver=lambda *_: ("8.8.8.8",), connection=origin.connection)
        with self.assertRaisesRegex(FetchError, "external_timeout"):
            fetcher.fetch("https://apk.example.com/slow", ["apk.example.com"], io.BytesIO())
        def untrusted(host, ip, timeout):
            return PinnedHTTPS(host, "127.0.0.1", timeout, port=origin.server.server_port)
        fetcher = ExternalFetcher(resolver=lambda *_: ("8.8.8.8",), connection=untrusted)
        with self.assertRaisesRegex(FetchError, "external_tls_failed"):
            fetcher.fetch("https://apk.example.com/file.apk", ["apk.example.com"], io.BytesIO())
