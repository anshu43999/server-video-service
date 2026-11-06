"""Rollback transaction, evidence and device semantics on SQLite / real PG."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.app_updates import contract as c
from app.app_updates.api import create_update_router
from app.app_updates.models import AppArtifact, AppArtifactSource, AppPolicy, AppRelease, AppRollback, AppAudit
from app.app_updates.service import UpdateError, now
from app.database import AccountRecord
import test_app_update_service as fixtures
from test_app_update_service import SCOPE, wire


class RollbackAssertions:
    seed = fixtures.ServiceAssertions.seed
    artifact = fixtures.ServiceAssertions.artifact
    draft = fixtures.ServiceAssertions.draft
    publish = fixtures.ServiceAssertions.publish
    check = fixtures.ServiceAssertions.check
    decode = fixtures.ServiceAssertions.decode
    report = fixtures.ServiceAssertions.report
    fail = fixtures.ServiceAssertions.fail
    def setup_rollback(self):
        self.seed()
        with self.db.session() as s:
            for a in s.scalars(select(AppArtifact)):
                a.build_provenance = {"compatibilityEvidenceRef": "trusted-build-test"}
        stable = self.service.draft("admin", self.draft(1))["resourceId"]
        self.service.publish("admin", self.publish(stable, version=1))
        bad = self.service.draft("admin", self.draft(2))["resourceId"]
        self.service.publish("admin", self.publish(bad, revision=2, floor=2, caps=["online.inference"]))
        recovery = self.service.draft("admin", self.draft(3))["resourceId"]
        self.service.recovery_evidence = [dict(stableSha256="1"*64, affectedSha256=["2"*64], recoverySha256="3"*64,
            preservesData=True, restoresStableBehavior=True, serverContractVersion=1, evidenceRef="trusted-recovery-test")]
        self.service.check(self.check(currentVersionCode=2))
        return wire(c.RollbackPreviewRequest, **SCOPE, expectedPolicyRevision=3,
            affectedReleaseIds=[bad], stableReleaseId=stable, recoveryReleaseId=recovery)

    def command(self, request, key="rollback"):
        preview = self.service.rollback_preview("admin", request)
        return wire(c.RollbackRequest, **request.model_dump(), previewFingerprint=preview["previewFingerprint"],
            idempotencyKey=key, reason="restore stable behavior")

    def test_atomic_recovery_signed_target_and_device_health(self):
        req = self.setup_rollback()
        before = self.service.read("admin", "audit")
        p = self.service.rollback_preview("admin", req)
        self.assertTrue(p["ready"])
        self.assertEqual((1,1,"ready"), (p["contactedDevices"],p["affectedDevices"],p["recoveryState"]))
        self.assertEqual(before, self.service.read("admin", "audit"))
        cmd = self.command(req)
        result = self.service.rollback_apply("admin", cmd)
        self.assertEqual(("applied",4,"ready"), (result["status"], result["effectivePolicyRevision"], result["recoveryState"]))
        self.assertEqual({"not_discovered":1}, result["deviceCounts"])
        self.assertEqual(result, self.service.rollback_apply("admin",cmd))
        check = self.check(currentVersionCode=2)
        target = self.decode(self.service.check(check),check).release
        self.assertEqual((3,"recovery",result["operationId"]), (target.versionCode,target.releasePurpose,target.rollbackOperationId))
        self.assertEqual(req.stableReleaseId,target.restoresBehaviorFromReleaseId)
        self.assertEqual(req.affectedReleaseIds,target.affectedReleaseIds)
        old = self.check(installationId="old", currentVersionCode=1)
        self.assertEqual("up_to_date", self.decode(self.service.check(old),old).result)
        report = self.report(req.recoveryReleaseId, currentVersionCode=2, artifactId="apk-3", sourceId="source-3",
            targetVersionCode=3, fromVersionCode=2, observedVersionCode=2, policyRevision=4, stage="installer_opened")
        self.service.receipt(report)
        self.assertEqual({"installer_opened":1},self.service.rollback_read("admin",result["operationId"])["deviceCounts"])
        healthy = report.model_copy(update=dict(eventId="healthy",sequence=2,currentVersionCode=3,
            observedVersionCode=3,stage="healthy"))
        self.service.receipt(healthy)
        self.assertEqual({"healthy":1},self.service.rollback_read("admin",result["operationId"])["deviceCounts"])
        with self.db.session() as s:
            policy=s.scalar(select(AppPolicy))
            self.assertEqual((1,[]),(policy.min_supported_version_code,policy.restricted_capabilities))
            self.assertEqual("stopped",s.get(AppRelease,req.affectedReleaseIds[0]).state)

    def test_pending_then_higher_recovery_and_fallback_stable(self):
        req=self.setup_rollback()
        pending=req.model_copy(update={"recoveryReleaseId":None})
        result=self.service.rollback_apply("admin",self.command(pending))
        self.assertEqual("pending",result["recoveryState"])
        check=self.check(currentVersionCode=2)
        self.assertEqual("recovery_pending",self.decode(self.service.check(check),check).result)
        old=self.check(installationId="old",currentVersionCode=1)
        self.assertEqual("up_to_date",self.decode(self.service.check(old),old).result)
        req=req.model_copy(update={"expectedPolicyRevision":4})
        result=self.service.rollback_apply("admin",self.command(req,key="ready"))
        self.assertEqual("ready",result["recoveryState"])
        self.assertEqual(3,self.decode(self.service.check(check),check).release.versionCode)

    def test_evidence_schema_source_and_low_version_reject_without_mutation(self):
        req=self.setup_rollback()
        cmd=self.command(req)
        with self.db.session() as s:
            s.get(AppArtifact,"apk-3").readable_schema_max=18
            s.get(AppArtifact,"apk-3").data_schema_version=18
        p=self.service.rollback_preview("admin",req)
        self.assertIn("recovery_data_incompatible",p["blockers"])
        self.fail("recovery_incompatible",self.service.rollback_apply,"admin",cmd)
        with self.db.session() as s:
            a=s.get(AppArtifact,"apk-3"); a.data_schema_version=19; a.readable_schema_max=19
        self.service.recovery_evidence=[]
        self.assertIn("recovery_evidence_missing",self.service.rollback_preview("admin",req)["blockers"])
        self.fail("recovery_incompatible",self.service.rollback_apply,"admin",cmd)
        with self.db.session() as s:
            self.assertEqual(3,s.scalar(select(AppPolicy.revision)))
            self.assertEqual("published",s.get(AppRelease,req.affectedReleaseIds[0]).state)
            self.assertEqual(0,s.scalar(select(func.count()).select_from(AppRollback)))

    def test_preview_fingerprint_expiry_source_change_and_transaction_failure(self):
        req=self.setup_rollback(); cmd=self.command(req)
        with self.db.session() as s:
            s.get(AppArtifactSource,"source-3").source_revision=2
        self.fail("rollback_preview_stale",self.service.rollback_apply,"admin",cmd)
        cmd=self.command(req)
        with patch("app.app_updates.rollback.now",return_value=now()+timedelta(minutes=6)):
            self.fail("rollback_preview_stale",self.service.rollback_apply,"admin",cmd)
        cmd=self.command(req)
        with patch.object(self.service,"snapshot",side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError): self.service.rollback_apply("admin",cmd)
        with self.db.session() as s:
            self.assertEqual(3,s.scalar(select(AppPolicy.revision)))
            self.assertEqual("draft",s.get(AppRelease,req.recoveryReleaseId).state)
            self.assertEqual("published",s.get(AppRelease,req.affectedReleaseIds[0]).state)
            self.assertEqual(0,s.scalar(select(func.count()).select_from(AppRollback)))

    def test_signature_size_protocol_low_version_and_revoked_source_rejected(self):
        req=self.setup_rollback()
        with self.db.session() as s: s.get(AppArtifact,"apk-3").signer_sha256="a"*64
        self.fail("signer_not_approved",self.service.rollback_preview,"admin",req)
        with self.db.session() as s:
            from test_app_update_service import SIGNER
            s.get(AppArtifact,"apk-3").signer_sha256=SIGNER
            s.get(AppArtifactSource,"source-3").verified_size_bytes=99
        self.fail("source_not_verified",self.service.rollback_preview,"admin",req)
        with self.db.session() as s:
            s.get(AppArtifactSource,"source-3").verified_size_bytes=100
            s.get(AppArtifact,"apk-3").server_contract_min=2
            s.get(AppArtifact,"apk-3").server_contract_max=2
        self.assertIn("build_compatibility_missing",self.service.rollback_preview("admin",req)["blockers"])
        with self.db.session() as s:
            a=s.get(AppArtifact,"apk-3"); a.server_contract_min=1; a.server_contract_max=1
            a.version_code=100
            s.get(AppArtifact,"apk-2").version_code=200
        self.assertIn("recovery_version_not_higher",self.service.rollback_preview("admin",req)["blockers"])
        with self.db.session() as s:
            s.get(AppArtifact,"apk-2").version_code=2
            s.get(AppArtifact,"apk-3").version_code=3
        cmd=self.command(req)
        with self.db.session() as s: s.get(AppArtifactSource,"source-3").availability_state="unavailable"
        self.fail("source_not_verified",self.service.rollback_apply,"admin",cmd)
        with self.db.session() as s: self.assertEqual(3,s.scalar(select(AppPolicy.revision)))

    def test_stopped_recovery_returns_pending_and_blocks_old_install(self):
        req=self.setup_rollback(); result=self.service.rollback_apply("admin",self.command(req))
        old=wire(c.InstallPermissionRequest,**SCOPE,requestId="old-install",installationId="device",currentVersionCode=1,
            expectedPolicyRevision=3,releaseId=req.affectedReleaseIds[0],artifactId="apk-2",sourceId="source-2",
            sourceRevision=1,sha256="2"*64,sizeBytes=100,verifiedVersionCode=2,
            verifiedSignerSha256=fixtures.SIGNER)
        self.fail("release_stopped",self.service.install,old)
        self.service.stop("admin",wire(c.StopRequest,**SCOPE,idempotencyKey="stop-recovery",reason="recovery fault",
            expectedPolicyRevision=result["effectivePolicyRevision"],releaseId=req.recoveryReleaseId))
        check=self.check(currentVersionCode=2)
        self.assertEqual("recovery_pending",self.decode(self.service.check(check),check).result)
        self.assertEqual("pending",self.service.rollback_read("admin",result["operationId"])["recoveryState"])

    def test_http_permissions_replay_and_operation_query(self):
        req=self.setup_rollback(); app=FastAPI(); app.include_router(create_update_router(lambda:self.service))
        client=TestClient(app); prefix="/aiyoloapi/admin/app-updates"
        headers={"Authorization":"Bearer app-update-session-token-long-enough"}
        with patch("app.auth.database",self.db):
            self.assertEqual(401,client.post(prefix+"/rollback-preview",json=req.model_dump()).status_code)
            response=client.post(prefix+"/rollback-preview",json=req.model_dump(),headers=headers)
            self.assertEqual(200,response.status_code,response.text)
            cmd=self.command(req)
            result=client.post(prefix+"/rollbacks",json=cmd.model_dump(),headers=headers)
            self.assertEqual(202,result.status_code,result.text)
            path=prefix+"/rollbacks/"+result.json()["operationId"]
            self.assertEqual(result.json(),client.get(path,headers=headers).json())
            self.assertEqual("no-store",client.get(path,headers=headers).headers["cache-control"])
            self.assertEqual(422,client.get(path+"?secret=x",headers=headers).status_code)
            changed=cmd.model_copy(update={"reason":"different"})
            self.assertEqual(409,client.post(prefix+"/rollbacks",json=changed.model_dump(),headers=headers).status_code)
            with self.db.session() as s: s.get(AccountRecord,"admin").platform_role="NORMAL_USER"
            self.assertEqual(403,client.get(path,headers=headers).status_code)
            self.assertEqual(403,client.post(prefix+"/rollbacks",json=cmd.model_dump(),headers=headers).status_code)


class SQLiteRollbackTests(RollbackAssertions, unittest.TestCase):
    setUp = fixtures.SQLiteServiceTests.setUp


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS")=="1","requires isolated PostgreSQL")
class PostgreSQLRollbackTests(RollbackAssertions, unittest.TestCase):
    setUp = fixtures.PostgreSQLServiceTests.setUp
    def test_concurrent_rollback_and_publish_have_one_winner(self):
        req=self.setup_rollback(); cmd=self.command(req)
        def attempt(fn, body):
            try: return fn("admin",body)
            except UpdateError as e: return e.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(attempt,self.service.rollback_apply,cmd)
            b=pool.submit(attempt,self.service.publish,self.publish(req.recoveryReleaseId,version=3,revision=3))
            results=[a.result(),b.result()]
        self.assertEqual(1,sum(isinstance(r,dict) for r in results))
        self.assertIn("policy_revision_conflict",results)

    def test_concurrent_identical_rollback_is_idempotent(self):
        req=self.setup_rollback(); cmd=self.command(req)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.service.rollback_apply("admin",cmd),range(2)))
        self.assertEqual(results[0],results[1])
        with self.db.session() as s:
            self.assertEqual(1,s.scalar(select(func.count()).select_from(AppRollback)))
            self.assertEqual(1,s.scalar(select(func.count()).select_from(AppAudit).where(AppAudit.action=="app_rollback")))
