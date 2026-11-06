"""Release/permission/report behavior on SQLite and isolated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import base64
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI
from fastapi.testclient import TestClient
from minio import Minio
from sqlalchemy import select

from app import auth
from app.app_updates import contract as c
from app.app_updates.api import RequestBudget, create_update_router
from app.app_updates.delivery import MinioTickets
from app.app_updates.models import (AppIdentity, AppArtifact, AppArtifactSource, AppPolicy,
    AppRelease, AppPolicyRevision, AppDeviceState, AppReceipt, AppAudit, AppUpload)
from app.app_updates.publisher import AppPublisher
from app.app_updates.service import AppUpdates, UpdateError, now
from app.app_updates.signatures import verify_envelope
from app.database import Base, DatabaseManager, AccountRecord, AccountSessionRecord
from postgresql_support import isolated_postgresql_url

ROOT = Path(__file__).resolve().parents[1]
SCOPE = dict(contractVersion=c.CONTRACT_VERSION, publisherId="test", packageName=c.PACKAGE_NAME,
    channel="enterprise-stable", deploymentId="test")
SIGNER = "b" * 64


def wire(model, **values):
    return model.model_validate_json(json.dumps(values))


class ServiceAssertions:
    def seed(self):
        self.publisher = AppPublisher("app-test", Ed25519PrivateKey.generate())
        self.service = AppUpdates(self.db, self.publisher, scopes=[SCOPE], gate_capabilities=["online.inference"])
        with self.db.session() as session:
            session.add(AccountRecord(account_id="admin", username="admin", role="admin", password_hash="test",
                platform_role="PLATFORM_ADMIN"))
            session.add(AccountSessionRecord(session_hash=auth._session_hash("app-update-session-token-long-enough"), account_id="admin",
                username="admin", role="admin", expires_at=now() + timedelta(hours=1)))
            session.add(AppIdentity(package_name=c.PACKAGE_NAME, publisher_id="test", approved_signer_sha256=SIGNER,
                metadata_key_config_ref=self.publisher.key_id, version_high_water=3))
        for version in (1, 2, 3):
            self.artifact(version)

    def artifact(self, version):
        with self.db.session() as session:
            session.add(AppArtifact(artifact_id=f"apk-{version}", package_name=c.PACKAGE_NAME, publisher_id="test",
                state="verified", version_code=version, version_name=str(version), size_bytes=100,
                sha256=str(version) * 64, signer_sha256=SIGNER, min_sdk=27, abis=["arm64-v8a"],
                server_contract_min=1, server_contract_max=1, data_schema_version=19,
                readable_schema_min=18, readable_schema_max=19, verification_evidence_ref="fixture",
                verified_at=now(), created_by="admin"))
            session.flush()
            session.add(AppArtifactSource(source_id=f"source-{version}", artifact_id=f"apk-{version}", source_revision=1,
                storage_mode="external", access_mode="public", public_url=f"https://apk.example.com/{version}.apk",
                allowed_hosts=["apk.example.com"], state="verified", verified_sha256=str(version) * 64,
                verified_size_bytes=100, verified_at=now(), verification_evidence_ref="fixture",
                availability_state="available", availability_checked_at=now(), created_by="admin"))

    def draft(self, version=2, importance="normal", key=None):
        return wire(c.ReleaseDraftRequest, **SCOPE, idempotencyKey=key or f"draft-{version}", reason="test draft",
            artifactId=f"apk-{version}", importance=importance, notes=["plain text release notes"])

    def publish(self, release, version=2, revision=1, floor=1, caps=None, key=None):
        return wire(c.PublishRequest, **SCOPE, idempotencyKey=key or f"publish-{version}", reason="test publish",
            releaseId=release, expectedPolicyRevision=revision, sourceId=f"source-{version}", sourceRevision=1,
            minSupportedVersionCode=floor, restrictedCapabilities=caps or [])

    def live(self, **kwargs):
        result = self.service.draft("admin", self.draft(importance=kwargs.pop("importance", "normal")))
        release = result["resourceId"]
        self.service.publish("admin", self.publish(release, **kwargs))
        return release

    def check(self, **changes):
        values = SCOPE | dict(requestId="check-test", installationId="device", currentVersionCode=1,
            currentVersionName="1", sdkInt=27, supportedAbis=["arm64-v8a"], signerSha256=SIGNER,
            serverContractVersion=1, lastPolicyRevision=0)
        return wire(c.CheckRequest, **(values | changes))

    def decode(self, envelope, body, kind="check", artifact=None):
        expected = body.model_dump(include=set(c.ClientContext.model_fields))
        if kind != "check":
            expected |= dict(releaseId=body.releaseId, artifactId=body.artifactId, sourceId=body.sourceId,
                sourceRevision=body.sourceRevision, versionCode=artifact or 2,
                sha256=body.sha256, sizeBytes=body.sizeBytes, signerSha256=SIGNER)
        return verify_envelope(json.dumps(envelope).encode(), trusted_keys={self.publisher.key_id:self.publisher.key.public_key()},
            message_type=kind, expected=expected, min_policy_revision=1)

    def download(self, release, revision=2, **extra):
        self.service.check(self.check())
        return wire(c.DownloadRequest, **(SCOPE | dict(requestId="download-test", installationId="device",
            currentVersionCode=1, expectedPolicyRevision=revision, releaseId=release, artifactId="apk-2",
            sourceId="source-2", sourceRevision=1, sha256="2" * 64, sizeBytes=100) | extra))

    def report(self, release, **extra):
        return wire(c.Receipt, **(SCOPE | dict(requestId="receipt-test", installationId="device", currentVersionCode=1,
            eventId="event", attemptId="attempt", sequence=1, policyRevision=2, releaseId=release, artifactId="apk-2",
            sourceId="source-2", sourceRevision=1, stage="discovered", fromVersionCode=1, targetVersionCode=2,
            observedVersionCode=1, occurredAt=now().isoformat(), errorCode=None) | extra))

    def fail(self, code, fn=None, *args):
        if fn is None:
            return super().fail(code)
        with self.assertRaisesRegex(UpdateError, "^" + code + "$"):
            fn(*args)

    def test_signed_check_download_install_and_stop(self):
        self.seed()
        release = self.live(importance="important")
        check = self.check()
        payload = self.decode(self.service.check(check), check)
        self.assertEqual("update_available", payload.result)
        self.assertEqual("important", payload.release.importance)
        request = self.download(release)
        signed = self.service.download(request)
        result = self.decode(signed, request, "download")
        self.assertEqual("https://apk.example.com/2.apk", result.downloadUrl)
        self.assertIsNone(result.downloadUrlExpiresAt)
        install = wire(c.InstallPermissionRequest, **request.model_dump(), verifiedVersionCode=2, verifiedSignerSha256=SIGNER)
        result = self.decode(self.service.install(install), install, "install_permission")
        self.assertTrue(result.userActionRequired)
        self.assertFalse(result.offlineInstallAllowed)
        self.assertLessEqual((result.authorizationExpiresAt-result.issuedAt).total_seconds(), 120)
        stop = wire(c.StopRequest, **SCOPE, idempotencyKey="stop", reason="halt release", releaseId=release,
            expectedPolicyRevision=2)
        self.service.stop("admin", stop)
        self.fail("release_stopped", self.service.download, request)
        self.fail("release_stopped", self.service.install, install)
        with self.db.session() as session:
            revisions = session.scalars(select(AppPolicyRevision).order_by(AppPolicyRevision.revision)).all()
            self.assertEqual([2, 3], [r.revision for r in revisions])
            for row in revisions:
                raw = base64.urlsafe_b64decode(row.payload_base64url + "=" * (-len(row.payload_base64url) % 4))
                signature = base64.urlsafe_b64decode(row.signature_base64url + "==")
                self.publisher.key.public_key().verify(signature, c.SIGNATURE_DOMAIN+raw)

    def test_idempotency_cas_immutability_and_reauthorization(self):
        self.seed()
        draft = self.draft()
        result = self.service.draft("admin", draft)
        self.assertEqual(result, self.service.draft("admin", draft))
        changed = draft.model_copy(update={"notes":["changed"]})
        self.fail("idempotency_conflict", self.service.draft, "admin", changed)
        request = self.publish(result["resourceId"])
        applied = self.service.publish("admin", request)
        self.assertEqual(applied, self.service.publish("admin", request))
        self.fail("policy_revision_conflict", self.service.publish, "admin", request.model_copy(update={"idempotencyKey":"new"}))
        with self.db.session() as session:
            session.get(AccountRecord, "admin").platform_role = "NORMAL_USER"
        self.fail("platform_admin_required", self.service.publish, "admin", request)
        with self.db.session() as session:
            self.assertEqual(2, session.get(AppPolicy, session.scalar(select(AppPolicy.policy_id))).revision)
            self.assertEqual(2, len(session.scalars(select(AppAudit)).all()))

    def test_sdk_abi_contract_signer_and_scope(self):
        self.seed()
        self.live()
        for changes, expected in [({"sdkInt":28}, "update_available"),
            ({"supportedAbis":["x86"]}, "no_compatible_release"),
            ({"signerSha256":"c"*64}, "client_unsupported"),
            ({"serverContractVersion":2}, "client_unsupported"),
            ({"currentVersionCode":2}, "up_to_date")]:
            with self.subTest(changes=changes):
                body=self.check(**changes)
                self.assertEqual(expected, self.decode(self.service.check(body),body).result)
        self.fail("deployment_not_allowed", self.service.check, self.check(deploymentId="other"))
        self.fail("policy_revision_conflict", self.service.check, self.check(lastPolicyRevision=100))
        with self.db.session() as session:
            session.get(AppArtifact,"apk-2").min_sdk=28
        body=self.check()
        self.assertEqual("no_compatible_release",self.decode(self.service.check(body),body).result)

    def test_binding_summary_and_source_checks(self):
        self.seed()
        release=self.live()
        body=self.download(release)
        for changes, code in [({"sha256":"f"*64},"artifact_not_verified"),({"sizeBytes":99},"artifact_not_verified"),
            ({"sourceRevision":2},"source_revision_conflict"),({"expectedPolicyRevision":1},"policy_revision_conflict"),
            ({"installationId":"unseen"},"compatibility_gate_unreachable"),
            ({"artifactId":"apk-3"},"source_revision_conflict")]:
            self.fail(code,self.service.download,body.model_copy(update=changes))
        with self.db.session() as session:
            session.get(AppArtifactSource,"source-2").availability_state="unavailable"
        self.fail("source_unavailable",self.service.download,body)
        check=self.check()
        self.assertEqual("no_compatible_release",self.decode(self.service.check(check),check).result)

    def test_install_verification_and_bounded_device_reports(self):
        self.seed()
        release=self.live()
        body=self.download(release)
        install=wire(c.InstallPermissionRequest,**body.model_dump(),verifiedVersionCode=2,verifiedSignerSha256=SIGNER)
        self.fail("signer_not_approved",self.service.install,install.model_copy(update={"verifiedSignerSha256":"c"*64}))
        self.fail("artifact_not_verified",self.service.install,install.model_copy(update={"verifiedVersionCode":3}))
        self.service.max_devices=1
        self.fail("rate_limited",self.service.check,self.check(installationId="another-device"))
        self.service.max_receipts=1
        first=self.report(release)
        self.service.receipt(first)
        self.assertTrue(self.service.receipt(first)["duplicate"])
        self.fail("rate_limited",self.service.receipt,self.report(release,eventId="second",sequence=2))

    def test_gate_reachable_and_protected_capabilities(self):
        self.seed()
        release=self.service.draft("admin",self.draft())["resourceId"]
        for floor,caps in [(3,["online.inference"]),(2,[]),(1,["online.inference"]),(2,["logout"])]:
            self.fail("compatibility_gate_unreachable",self.service.publish,"admin",self.publish(release,floor=floor,caps=caps))
        self.service.publish("admin",self.publish(release,floor=2,caps=["online.inference"]))
        request=self.check()
        result=self.decode(self.service.check(request),request)
        self.assertEqual("restrict_declared_capabilities",result.compatibility.onlineAction)
        self.assertEqual(["online.inference"],result.compatibility.restrictedCapabilities)

    def test_gate_rejects_contacted_incompatible_device(self):
        self.seed()
        self.service.draft("admin",self.draft())
        self.service.check(self.check(supportedAbis=["x86"]))
        with self.db.session() as session:
            release=session.scalar(select(AppRelease.release_id))
        self.fail("compatibility_gate_unreachable",self.service.publish,"admin",self.publish(release,floor=2,caps=["online.inference"]))
        with self.db.session() as session:
            self.assertEqual("draft",session.get(AppRelease,release).state)
            self.assertEqual([],session.scalars(select(AppPolicyRevision)).all())

    def test_report_deduplication_and_terminal_projection(self):
        self.seed()
        release=self.live()
        first=self.report(release)
        accepted=self.service.receipt(first)
        duplicate=self.service.receipt(first)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(accepted["receivedAt"],duplicate["receivedAt"])
        self.fail("idempotency_conflict",self.service.receipt,first.model_copy(update={"requestId":"changed"}))
        self.fail("idempotency_conflict",self.service.receipt,first.model_copy(update={"eventId":"other"}))
        self.service.receipt(self.report(release,eventId="healthy",sequence=8,stage="healthy",observedVersionCode=2,currentVersionCode=2))
        self.service.receipt(self.report(release,eventId="late",sequence=3,stage="downloaded"))
        self.service.receipt(self.report(release,eventId="wrong-later",sequence=10,stage="downloaded"))
        with self.db.session() as session:
            device=session.scalar(select(AppDeviceState))
            self.assertEqual("healthy",device.stage)
            self.assertEqual(2,device.current_version_code)
            self.assertEqual(4,len(session.scalars(select(AppReceipt)).all()))

    def test_old_attempt_cannot_replace_new_attempt(self):
        self.seed()
        release=self.live()
        self.service.receipt(self.report(release))
        self.service.receipt(self.report(release,eventId="new",attemptId="new-attempt",sequence=1,stage="downloading"))
        self.service.receipt(self.report(release,eventId="old-health",sequence=9,stage="healthy",observedVersionCode=2))
        with self.db.session() as session:
            device=session.scalar(select(AppDeviceState))
            self.assertEqual("new-attempt",device.attempt_id)
            self.assertEqual("downloading",device.stage)

    def test_attempt_identity_cannot_change_artifact(self):
        self.seed()
        release=self.live()
        self.service.receipt(self.report(release))
        draft=self.service.draft("admin",self.draft(3))
        self.service.publish("admin",self.publish(draft["resourceId"],version=3,revision=2))
        changed=self.report(draft["resourceId"],eventId="changed-attempt",sequence=2,artifactId="apk-3",
            sourceId="source-3",targetVersionCode=3,policyRevision=3)
        self.fail("idempotency_conflict",self.service.receipt,changed)

    def test_receipt_checks_historical_published_binding_after_stop(self):
        self.seed()
        release=self.live()
        self.fail("invalid_request",self.service.receipt,self.report(release,sourceRevision=2))
        self.fail("invalid_request",self.service.receipt,self.report(release,policyRevision=1))
        self.service.stop("admin",wire(c.StopRequest,**SCOPE,idempotencyKey="stop",reason="halt",releaseId=release,expectedPolicyRevision=2))
        result=self.service.receipt(self.report(release,stage="installer_opened"))
        self.assertTrue(result["accepted"])
        with self.db.session() as session:
            self.assertEqual("installer_opened",session.scalar(select(AppDeviceState.stage)))

    def test_projection_pagination_and_no_sensitive_location(self):
        self.seed()
        self.live()
        page=self.service.read("admin","artifacts",limit=1)
        ids=[page["items"][0]["resourceId"]]
        while page["nextCursor"]:
            page=self.service.read("admin","artifacts",limit=1,cursor=page["nextCursor"])
            ids.extend(row["resourceId"] for row in page["items"])
        self.assertEqual(3,len(set(ids)))
        sources=self.service.read("admin","sources",artifact_id="apk-2")
        self.assertNotIn("https://",json.dumps(sources))
        self.assertNotIn("verification_evidence_ref",json.dumps(sources))
        for cursor in ("!",base64.urlsafe_b64encode(b'[]').decode(),base64.urlsafe_b64encode(b'{}').decode()):
            with self.assertRaises(UpdateError):
                self.service.read("admin","artifacts",cursor=cursor)

    def test_http_current_admin_public_signed_routes_and_validation(self):
        self.seed()
        app=FastAPI()
        app.include_router(create_update_router(lambda:self.service))
        client=TestClient(app)
        prefix="/aiyoloapi/admin/app-updates"
        headers={"Authorization":"Bearer app-update-session-token-long-enough"}
        with patch("app.auth.database",self.db):
            self.assertEqual(401,client.post(prefix+"/releases",json=self.draft().model_dump()).status_code)
            draft=client.post(prefix+"/releases",json=self.draft().model_dump(),headers=headers)
            self.assertEqual(201,draft.status_code,draft.text)
            release=draft.json()["resourceId"]
            self.assertEqual(422,client.post(prefix+"/releases/wrong/publish",json=self.publish(release).model_dump(),headers=headers).status_code)
            published=client.post(prefix+f"/releases/{release}/publish",json=self.publish(release).model_dump(),headers=headers)
            self.assertEqual(200,published.status_code,published.text)
            check=client.post("/aiyoloapi/mobile/app-updates/check",json=self.check().model_dump())
            self.assertEqual(200,check.status_code,check.text)
            self.decode(check.json(),self.check())
            download=self.download(release)
            response=client.post(f"/aiyoloapi/mobile/app-updates/{release}/download-ticket",json=download.model_dump())
            self.assertEqual(200,response.status_code,response.text)
            response=client.post("/aiyoloapi/mobile/app-updates/receipts",json=self.report(release).model_dump(mode="json"))
            self.assertEqual(200,response.status_code,response.text)
            response=client.post("/aiyoloapi/mobile/app-updates/check",content='{"secret":"https://user:pass@host"}',headers={"Content-Type":"application/json"})
            self.assertEqual(422,response.status_code)
            self.assertEqual(set(c.ErrorBody.model_fields),set(response.json()))
            self.assertNotIn("user:pass",response.text)
            response=client.post("/aiyoloapi/mobile/app-updates/check",content='{"contractVersion":"other"}',headers={"Content-Type":"application/json"})
            self.assertEqual(426,response.status_code)
            self.assertEqual(422,client.get(prefix+"/artifacts?limit=101",headers=headers).status_code)
            with self.db.session() as session:
                session.get(AccountRecord,"admin").platform_role="NORMAL_USER"
            self.assertEqual(403,client.get(prefix+"/artifacts",headers=headers).status_code)
            with patch.object(auth.settings,"deployment_env","development"),patch.object(auth.settings,"admin_token","legacy-fixture"):
                self.assertEqual(403,client.get(prefix+"/artifacts",headers={"x-admin-token":"legacy-fixture"}).status_code)
            with self.db.session() as session:
                session.get(AccountRecord,"admin").enabled=False
            self.assertEqual(401,client.get(prefix+"/artifacts",headers=headers).status_code)

    def test_admin_configuration_jobs_and_current_authorization(self):
        self.seed()
        self.service.upload_enabled = True
        self.service.external_enabled = True
        with self.db.session() as session:
            for index in range(12):
                session.add(AppUpload(upload_id=f"job-{index:02}", actor_id="admin", artifact_id="apk-2",
                    state="failed", kind="external", external_url="https://apk.example.com/a.apk?secret=private",
                    external_hosts=["apk.example.com"], error_code="apk_invalid", lease_until=now(),
                    fetch_evidence={"path":"private-local-path"}, created_at=now()+timedelta(seconds=index)))
        jobs=self.service.read("admin","artifacts",resource_id="apk-2")["details"]["jobs"]
        self.assertEqual(10,len(jobs))
        self.assertEqual("job-11",jobs[0]["jobId"])
        self.assertNotIn("secret",json.dumps(jobs))
        self.assertNotIn("private-local-path",json.dumps(jobs))
        budget=RequestBudget(rate=20)
        app=FastAPI(); app.include_router(create_update_router(lambda:self.service,budget=budget))
        client=TestClient(app)
        path="/aiyoloapi/admin/app-updates/configuration"
        headers={"Authorization":"Bearer app-update-session-token-long-enough"}
        with patch("app.auth.database",self.db):
            response=client.get(path,headers=headers)
            self.assertEqual(200,response.status_code,response.text)
            self.assertEqual("no-store",response.headers["cache-control"])
            self.assertEqual(dict(scopes=[SCOPE],gateCapabilities=["online.inference"],
                maxApkBytes=8*1024**3,uploadEnabled=True,externalEnabled=True),response.json())
            self.assertEqual(422,client.get(path+"?unexpected=1",headers=headers).status_code)
            self.assertEqual(0,budget.active)
            budget.rate=0
            self.assertEqual(429,client.get(path,headers=headers).status_code)
            budget.rate=20
            self.assertEqual(401,client.get(path).status_code)
            with self.db.session() as session:
                session.get(AccountRecord,"admin").platform_role="NORMAL_USER"
            self.assertEqual(403,client.get(path,headers=headers).status_code)
            self.fail("platform_admin_required",self.service.configuration,"admin")
            with patch.object(auth.settings,"deployment_env","development"),patch.object(auth.settings,"admin_token","legacy-fixture"):
                self.assertEqual(403,client.get(path,headers={"x-admin-token":"legacy-fixture"}).status_code)
            with self.db.session() as session:
                session.get(AccountRecord,"admin").enabled=False
            self.assertEqual(401,client.get(path,headers=headers).status_code)


class SQLiteServiceTests(ServiceAssertions, unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="app-publish-",dir=ROOT/".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=DatabaseManager("sqlite:///"+(self.root/"test.db").as_posix())
        Base.metadata.create_all(self.db.engine)
        self.addCleanup(self.db.close)


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS")=="1","requires isolated PostgreSQL")
class PostgreSQLServiceTests(ServiceAssertions, unittest.TestCase):
    def setUp(self):
        cluster=isolated_postgresql_url("app_publish")
        self.db=DatabaseManager(cluster.__enter__())
        self.addCleanup(lambda:cluster.__exit__(None,None,None))
        self.addCleanup(self.db.close)

    def test_concurrent_publish_stop_and_receipt(self):
        self.seed()
        release=self.service.draft("admin",self.draft())["resourceId"]
        second=self.service.draft("admin",self.draft(3))["resourceId"]
        def publish(request):
            try:
                return self.service.publish("admin",request)["state"]
            except UpdateError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(publish,[self.publish(release),self.publish(second,version=3)]))
        self.assertEqual(["policy_revision_conflict","published"],sorted(results))
        with self.db.session() as session:
            chosen=session.scalar(select(AppRelease).where(AppRelease.state=="published"))
            release,artifact=chosen.release_id,chosen.artifact_id
            version=int(artifact[-1])
        body=self.report(release,artifactId=artifact,sourceId=f"source-{version}",targetVersionCode=version)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(self.service.receipt,[body,body]))
        self.assertEqual([False,True],sorted(r["duplicate"] for r in results))
        self.service.check(self.check())
        download=wire(c.DownloadRequest,**SCOPE,requestId="race",installationId="device",currentVersionCode=1,
            expectedPolicyRevision=2,releaseId=release,artifactId=artifact,sourceId=f"source-{version}",sourceRevision=1,
            sha256=str(version)*64,sizeBytes=100)
        stop=wire(c.StopRequest,**SCOPE,expectedPolicyRevision=2,releaseId=release,idempotencyKey="stop",reason="concurrent stop")
        def issue(_):
            try:
                return self.service.download(download)
            except UpdateError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            ticket=pool.submit(issue,0)
            stopped=pool.submit(self.service.stop,"admin",stop)
            ticket.result()
            self.assertEqual("stopped",stopped.result()["state"])
        self.fail("release_stopped",self.service.download,download)
        with self.db.session() as session:
            self.assertEqual(1,len(session.scalars(select(AppReceipt)).all()))


class SigningAndMinioTests(unittest.TestCase):
    def test_http_budget_and_duplicate_json_rejected(self):
        app=FastAPI()
        app.include_router(create_update_router(lambda:None,budget=RequestBudget(rate=1)))
        client=TestClient(app)
        url="/aiyoloapi/mobile/app-updates/check"
        body='{"contractVersion":"app-update/v1","contractVersion":"other"}'
        response=client.post(url,content=body,headers={"Content-Type":"application/json"})
        self.assertEqual(422,response.status_code)
        response=client.post(url,content=body,headers={"Content-Type":"application/json"})
        self.assertEqual(429,response.status_code)
        self.assertEqual("60",response.headers["Retry-After"])
        self.assertEqual("rate_limited",response.json()["code"])

    def test_minio_ticket_pins_version_and_https_without_proxy(self):
        minio=Minio("files.example.com",access_key="test-access",secret_key="test-secret",secure=True,region="us-east-1")
        store=SimpleNamespace(client=minio,bucket="apks")
        issue=MinioTickets(store)
        source=SimpleNamespace(bucket="apks",object_key="app/2.apk",object_version_id="version-one",
            object_etag="etag",allowed_hosts=["files.example.com"])
        artifact=SimpleNamespace(size_bytes=100)
        start=now()
        with patch.object(minio,"stat_object",return_value=SimpleNamespace(size=100,etag="etag")) as stat:
            url,expiry=issue(source,artifact,start,start+timedelta(seconds=900))
        self.assertIn("versionId=version-one",url)
        self.assertTrue(url.startswith("https://files.example.com/apks/app/2.apk?"))
        self.assertGreater(expiry,start+timedelta(seconds=900))
        self.assertEqual("version-one",stat.call_args.kwargs["version_id"])
        source.allowed_hosts=["other.example.com"]
        with patch.object(minio,"stat_object",return_value=SimpleNamespace(size=100,etag="etag")):
            with self.assertRaisesRegex(ValueError,"approved HTTPS"):
                issue(source,artifact,start,start+timedelta(seconds=900))

    def test_signer_rejects_reused_model_key(self):
        with tempfile.TemporaryDirectory(prefix="app-key-",dir=ROOT/".tmp") as directory:
            path=Path(directory)/"key.pem"
            key=Ed25519PrivateKey.generate()
            path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            settings=SimpleNamespace(app_update_private_key_path=path,app_update_key_id="app",
                model_signing_private_key_path=path)
            with self.assertRaisesRegex(ValueError,"independent"):
                AppPublisher.from_settings(settings)
