"""M42-T08: real sessions/transactions, bounded endpoints and hostile sources."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from app import auth
from app.app_updates import contract as c
from app.app_updates.api import RequestBudget, create_update_router
from app.app_updates.external_api import create_external_router
from app.app_updates.external_fetch import FetchError
from app.app_updates.external_jobs import ExternalJobs
from app.app_updates.models import AppArtifactSource, AppAudit, AppPolicy, AppRelease, AppUpload
from app.app_updates.security import SessionActor, audit_text
from app.app_updates.service import UpdateError, now
from app.app_updates.upload_api import create_upload_router
from app.app_updates.uploads import ApkUploads, UploadError
from app.database import AccountRecord, AccountSessionRecord, Base, DatabaseManager, ProjectRecord, ProjectMembershipRecord
from app.observability import RequestTelemetry
from postgresql_support import isolated_postgresql_url
import test_app_update_service as releases
import test_apk_uploads as uploads
import test_apk_external as external

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/aiyoloapi/admin/app-updates"
TOKEN = "app-update-session-token-long-enough"
HEADERS = {"Authorization": "Bearer " + TOKEN}


class SecurityAssertions:
    seed = releases.ServiceAssertions.seed
    artifact = releases.ServiceAssertions.artifact
    draft = releases.ServiceAssertions.draft
    publish = releases.ServiceAssertions.publish

    def clients(self, *, budget=None, update_provider=None, upload_provider=None, external_provider=None):
        self.seed()
        self.uploads = ApkUploads(self.db, uploads.Verifier(), uploads.Store(), root=self.root / "uploads",
            compatibility=uploads.COMPAT)
        fetch, self.transport = external.fetcher([external.Response()])
        self.external = ExternalJobs(self.db, uploads.Verifier(), fetch, root=self.root / "external",
            compatibility=uploads.COMPAT)
        app = FastAPI()
        self.update_router = create_update_router(update_provider or (lambda: self.service), budget=budget)
        self.upload_router = create_upload_router(upload_provider or (lambda: self.uploads), max_bytes=1000,
            receive_seconds=30, budget=budget)
        self.external_router = create_external_router(external_provider or (lambda: self.external), budget=budget)
        for router in (self.update_router, self.upload_router, self.external_router):
            app.include_router(router)
        self.client = TestClient(app)
        self.enterContext(patch("app.auth.database", self.db))
        self.enterContext(patch.object(auth.settings, "deployment_env", "production"))

    def change_session(self, mode):
        with self.db.session() as session:
            row = session.get(AccountSessionRecord, auth._session_hash(TOKEN))
            if mode == "expired":
                row.expires_at = now() - timedelta(seconds=1)
            elif mode == "revoked":
                row.revoked_at = now()
            elif mode == "disabled":
                session.get(AccountRecord, "admin").enabled = False
            else:
                session.get(AccountRecord, "admin").platform_role = "NORMAL_USER"
                if mode == "project_admin":
                    project_id = "ff432198-2f32-4cdd-8296-ecba0a696271"
                    session.add(ProjectRecord(project_id=project_id,project_code="update-security",
                        display_name="Update security test"))
                    session.flush()
                    session.add(ProjectMembershipRecord(project_id=project_id,account_id="admin",
                        project_role="PROJECT_OWNER",enabled=True))

    def restore(self):
        with self.db.session() as session:
            row = session.get(AccountSessionRecord, auth._session_hash(TOKEN))
            row.expires_at, row.revoked_at = now() + timedelta(hours=1), None
            account = session.get(AccountRecord, "admin")
            account.enabled, account.platform_role = True, "PLATFORM_ADMIN"

    def test_every_management_write_rechecks_current_identity(self):
        self.clients()
        paths = ["/releases", "/releases/test/publish", "/releases/test/stop", "/rollback-preview",
                 "/rollbacks", "/external-artifacts", "/artifacts/test/download-sources", "/artifacts/upload"]
        for mode in ("normal", "project_admin", "revoked", "expired", "disabled"):
            self.change_session(mode)
            for path in paths:
                with self.subTest(mode=mode, path=path):
                    response = self.client.post(PREFIX + path, content=b"must not be parsed", headers=HEADERS)
                    self.assertEqual(403 if mode in ("normal", "project_admin") else 401, response.status_code)
                    self.assertEqual("no-store", response.headers["cache-control"])
            self.restore()
        with patch.object(auth.settings, "deployment_env", "development"), patch.object(auth.settings, "admin_token", "legacy-secret"):
            for path in paths:
                self.assertEqual(403, self.client.post(PREFIX+path, content=b"unused",
                    headers={"X-Admin-Token": "legacy-secret"}).status_code)
        with self.db.session() as session:
            self.assertEqual([], session.scalars(select(AppUpload)).all())
            self.assertEqual([], session.scalars(select(AppRelease)).all())

    def test_revocation_while_json_body_arrives_is_rejected(self):
        self.clients()
        for router, body in ((self.update_router, self.draft().model_dump()),
                             (self.external_router, external.request().model_dump())):
            endpoint = next(r.endpoint for r in router.routes if r.path.endswith("/releases") or r.path.endswith("/external-artifacts"))
            async def receive():
                self.change_session("revoked")
                return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
            request = Request({"type":"http", "query_string":b"", "headers":[
                (b"authorization", HEADERS["Authorization"].encode()), (b"content-type",b"application/json")]}, receive)
            if router is self.update_router:
                self.assertEqual(401, asyncio.run(endpoint(request)).status_code)
            else:
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(endpoint(request))
                self.assertEqual(401, caught.exception.status_code)
            self.restore()

    def test_revocation_after_admission_is_rechecked_under_transaction(self):
        self.clients()
        body = self.draft()
        def revoke_then_call(actor, request):
            self.change_session("revoked")
            return original(actor, request)
        original = self.service.draft
        with patch.object(self.service, "draft", side_effect=revoke_then_call):
            response = self.client.post(PREFIX+"/releases", json=body.model_dump(), headers=HEADERS)
        self.assertEqual(401, response.status_code)
        with self.db.session() as session:
            self.assertEqual([], session.scalars(select(AppRelease)).all())
            audit = session.scalar(select(AppAudit))
            self.assertEqual("rejected", audit.result)
            self.assertEqual("authentication_required", audit.details["errorCode"])

    def test_upload_revoked_before_commit_cleans_and_does_not_queue(self):
        self.clients()
        original = self.uploads.finish
        def revoke_then_finish(*args, **kwargs):
            self.change_session("expired")
            return original(*args, **kwargs)
        with patch.object(self.uploads, "finish", side_effect=revoke_then_finish):
            response = self.client.post(PREFIX+"/artifacts/upload", headers=HEADERS,
                files={"apk":("file.apk", b"one")}, data={"idempotencyKey":"test", "reason":"test"})
        self.assertEqual(401, response.status_code)
        self.assertEqual([], list(self.uploads.root.glob("*.apk")))
        with self.db.session() as session:
            row = session.scalar(select(AppUpload))
            self.assertEqual("failed", row.state)
            self.assertEqual("authentication_required", row.error_code)

    def test_external_transaction_rejects_revoked_session(self):
        self.clients()
        actor = SessionActor("admin", auth._session_hash(TOKEN))
        self.change_session("revoked")
        with self.assertRaisesRegex(UploadError, "authentication_required"):
            self.external.register(actor, external.request())

    def test_ingress_budget_duplicate_json_queries_and_release(self):
        budget = RequestBudget(rate=20, concurrent=1)
        self.clients(budget=budget)
        body = json.dumps(external.request().model_dump())
        duplicate = body[:-1] + ',"reason":"ambiguous"}'
        for path, raw in (("/external-artifacts", duplicate), ("/releases", '{"a":1,"a":2}')):
            response = self.client.post(PREFIX+path, content=raw, headers=HEADERS|{"Content-Type":"application/json"})
            self.assertEqual(422, response.status_code)
            self.assertEqual(0, budget.active)
        for path in ("/external-artifacts", "/artifacts/upload", "/releases"):
            response = self.client.post(PREFIX+path+"?token=sensitive-query", headers=HEADERS, json={})
            self.assertEqual(422, response.status_code)
            self.assertNotIn("sensitive-query", response.text)
            self.assertEqual("no-store", response.headers["cache-control"])
            self.assertEqual(0, budget.active)
        budget.enter("held")
        try:
            for path in ("/external-artifacts", "/artifacts/upload", "/releases"):
                response = self.client.post(PREFIX+path, headers=HEADERS, json={})
                self.assertEqual(429, response.status_code)
                self.assertEqual("60", response.headers["retry-after"])
                self.assertEqual(1, budget.active)
        finally:
            budget.leave()

    def test_database_errors_do_not_leak(self):
        budget = RequestBudget()
        def broken():
            raise OperationalError("sql-sensitive", {"password":"private-value"}, Exception("secret-connection"))
        self.clients(budget=budget, update_provider=broken, upload_provider=broken, external_provider=broken)
        for path in ("/external-artifacts", "/artifacts/upload", "/releases"):
            kwargs = {"json": self.draft().model_dump() if path == "/releases" else external.request().model_dump()}
            if path == "/artifacts/upload":
                kwargs = dict(files={"apk":("f.apk",b"x")}, data={"reason":"test","idempotencyKey":"test"})
            response = self.client.post(PREFIX+path, headers=HEADERS, **kwargs)
            self.assertEqual(503, response.status_code, response.text)
            self.assertFalse(any(value in response.text for value in ("private-value","sql-sensitive","secret-connection")))
            self.assertEqual(0, budget.active)

    def test_failed_upload_cleanup_database_error_releases_budget(self):
        budget = RequestBudget()
        self.clients(budget=budget)
        error = OperationalError("sql-sensitive", {}, Exception("secret-connection"))
        with patch.object(self.uploads,"fail_receive",side_effect=error):
            response = self.client.post(PREFIX+"/artifacts/upload", headers=HEADERS,
                files={"apk":("file.apk", b"x"*1001)},data={"idempotencyKey":"test","reason":"test"})
        self.assertEqual(413,response.status_code)
        self.assertNotIn("sql-sensitive",response.text)
        self.assertEqual(0,budget.active)
        with self.db.session() as session:
            job = session.scalar(select(AppUpload))
            self.assertEqual("receiving",job.state)
            job.lease_until = now()-timedelta(seconds=1)
        self.uploads.recover()
        self.assertEqual([],list(self.uploads.root.glob("*.apk")))

    def test_deep_json_rejected_without_server_error(self):
        self.clients()
        for path in ("/external-artifacts","/releases"):
            response = self.client.post(PREFIX+path,headers=HEADERS|{"Content-Type":"application/json"},
                content=b'['*1500+b'0'+b']'*1500)
            self.assertEqual(422,response.status_code)

    def test_redacted_audit_still_binds_request_artifact_source_and_revisions(self):
        self.clients()
        secret = "repair https://apk.example.com/file?token=url-secret password=pass-secret Bearer bearer-secret"
        body = self.draft().model_copy(update={"reason":secret})
        result = self.service.draft("admin", body)
        self.assertEqual(result, self.service.draft("admin", body))
        publish = self.publish(result["resourceId"]).model_copy(update={"reason":secret})
        self.service.publish("admin", publish)
        response = self.client.post(PREFIX+f"/releases/{result['resourceId']}/publish", headers=HEADERS,
            json=publish.model_copy(update={"idempotencyKey":"stale"}).model_dump())
        self.assertEqual(409, response.status_code)
        with self.db.session() as session:
            rows = session.scalars(select(AppAudit)).all()
            encoded = json.dumps([dict(reason=r.reason,details=r.details) for r in rows])
            self.assertFalse(any(s in encoded for s in ("url-secret","pass-secret","bearer-secret","https://")))
            row = next(r for r in rows if r.action == "app_release_publish")
            self.assertEqual((1,2), (row.before_revision,row.after_revision))
            self.assertEqual(["apk-2"], row.details["artifactIds"])
            self.assertTrue(any(b["sourceId"] == "source-2" and b["sourceRevision"] == 1 for b in row.details["sourceBindings"]))
            rejected = next(r for r in rows if r.result == "rejected")
            self.assertEqual("policy_revision_conflict", rejected.details["errorCode"])
            self.assertNotEqual(row.request_sha256, rejected.request_sha256)
        self.assertNotIn("url-secret", json.dumps(self.service.read("admin","audit")))

    def test_both_job_audits_redact_reasons_and_cleanup_only_terminal(self):
        self.clients()
        secret = "reason https://apk.example.com/file?signature=hidden-url secret=hidden-value"
        req = external.request().model_copy(update={"reason":secret})
        self.external.register("admin", req)
        self.external.process_one()  # Fixture version 1 already exists with different bytes: fail closed.
        upload = self.uploads.begin("admin")
        self.uploads.path(upload).write_bytes(b"one")
        self.assertFalse(self.uploads.cleanup(upload))
        self.assertTrue(self.uploads.path(upload).exists())
        self.uploads.finish(upload, idempotency_key="upload", reason=secret, size_bytes=3,
            sha256=hashlib.sha256(b"one").hexdigest())
        self.uploads.fail_receive(upload,"unused")  # queued job must remain untouched
        self.assertTrue(self.uploads.path(upload).exists())
        with self.db.session() as session:
            rows = session.scalars(select(AppAudit)).all()
            self.assertFalse(any("hidden-" in r.reason for r in rows))
            jobs = session.scalars(select(AppUpload)).all()
            self.assertFalse(any("hidden-" in j.reason for j in jobs))
        self.uploads.process_one()
        self.assertEqual([], list(self.uploads.root.glob("*.apk")))

    def test_worker_exception_code_is_not_trusted_audit_input(self):
        self.clients()
        class UnexpectedError(Exception):
            code = "https://host.example/path?secret=do-not-log"
        self.external.register("admin",external.request())
        with patch.object(self.external.fetcher,"fetch",side_effect=UnexpectedError()):
            self.external.process_one()
        with self.db.session() as session:
            row = session.scalar(select(AppUpload))
            self.assertEqual("external_internal_error",row.error_code)
            encoded = json.dumps([r.details for r in session.scalars(select(AppAudit))])
            self.assertNotIn("do-not-log",encoded)

    def test_retired_source_projection_is_safe_and_unusable(self):
        self.clients()
        with self.db.session() as session:
            session.get(AppArtifactSource,"source-2").state = "retired"
        value = self.service.read("admin","sources",artifact_id="apk-2")["items"][0]
        self.assertEqual("failed",value["state"])
        self.assertEqual("retired",value["details"]["sourceState"])
        release = self.service.draft("admin",self.draft())["resourceId"]
        with self.assertRaisesRegex(UpdateError,"source_not_verified"):
            self.service.publish("admin",self.publish(release))


class SQLiteSecurityTests(SecurityAssertions, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="update-security-", dir=ROOT/".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = DatabaseManager("sqlite+pysqlite:///"+(self.root/"test.db").as_posix())
        Base.metadata.create_all(self.db.engine)
        self.addCleanup(self.db.close)


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL")
class PostgreSQLSecurityTests(SecurityAssertions, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="update-security-pg-", dir=ROOT/".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cluster = isolated_postgresql_url("update_security")
        url = cluster.__enter__()
        self.addCleanup(lambda:cluster.__exit__(None,None,None))
        self.db = DatabaseManager(url)
        self.addCleanup(self.db.close)

    def test_concurrent_upload_completion_keeps_one_idempotent_job(self):
        self.clients()
        ids = [self.uploads.begin("admin") for _ in range(2)]
        for identity in ids:
            self.uploads.path(identity).write_bytes(b"same")
        def finish(identity):
            return self.uploads.finish(identity,idempotency_key="parallel",reason="test",size_bytes=4,
                sha256=hashlib.sha256(b"same").hexdigest())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(finish,ids))
        self.assertEqual(results[0],results[1])
        with self.db.session() as session:
            jobs = session.scalars(select(AppUpload)).all()
            self.assertEqual(["failed","queued"],sorted(j.state for j in jobs))
        self.assertEqual(1,len(list(self.uploads.root.glob("*.apk"))))


class HostileSourceTests(unittest.TestCase):
    def test_redirect_controls_duplicate_location_and_framing_rejected(self):
        responses = []
        for location in ("/new\r\nInjected:yes", " /space", "/tab\there", "https://apk.example.com\\evil"):
            responses.append(external.Response(status=302,Location=location))
        duplicate = external.Response(status=302,Location="/one")
        duplicate.headers["Location"] = "/two"
        responses.append(duplicate)
        for headers in (("Content-Length","1"),("Transfer-Encoding","gzip")):
            response = external.Response(**{"Content_Length":len(external.RAW)}) if headers[0] == "Content-Length" else external.Response()
            response.headers[headers[0]] = headers[1]
            responses.append(response)
        for response in responses:
            fetch, transport = external.fetcher([response])
            with self.assertRaises(FetchError):
                fetch.fetch("https://apk.example.com/a?token=sensitive", ["apk.example.com"],io.BytesIO())
            self.assertEqual(1,len(transport.calls))
            self.assertTrue(transport.connections[0].closed)

    def test_rebinding_checks_every_hop_and_evidence_has_no_full_url(self):
        fetch, transport = external.fetcher([external.Response(status=302,Location="/new"),external.Response()])
        answers = iter([("8.8.8.8",),("10.0.0.1",)])
        fetch.resolver = lambda *_:next(answers)
        with self.assertRaisesRegex(FetchError,"external_address_forbidden"):
            fetch.fetch("https://apk.example.com/a",["apk.example.com"],io.BytesIO())
        self.assertEqual(1,len(transport.calls))
        fetch, _ = external.fetcher([external.Response()])
        result = fetch.fetch("https://apk.example.com/a?secret=sensitive",["apk.example.com"],io.BytesIO())
        self.assertNotIn("sensitive",json.dumps(result.evidence))
        self.assertNotIn("https://",json.dumps(result.evidence))

    def test_telemetry_uses_route_template_and_server_request_id(self):
        app = FastAPI()
        @app.get("/items/{item_id}")
        async def item(item_id:str):
            return {"ok":True}
        app.add_middleware(RequestTelemetry)
        with patch.object(logging.getLogger("aiyolo.requests"),"info") as log:
            response = TestClient(app).get("/items/private-path?token=query-secret",headers={"X-Request-ID":"header-secret"})
        encoded = json.dumps(log.call_args_list,default=str)
        self.assertFalse(any(s in encoded for s in ("query-secret","header-secret","private-path")))
        self.assertNotEqual("header-secret",response.headers["x-request-id"])
        self.assertIn("/items/{item_id}",encoded)

    def test_private_key_reason_is_redacted(self):
        self.assertNotIn("key-material",audit_text("urgent -----BEGIN PRIVATE KEY-----\nkey-material\n-----END PRIVATE KEY-----"))
