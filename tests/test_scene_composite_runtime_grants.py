"""M39: all-or-nothing leases, compatible single grants and cross-worker races."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Barrier, Event, RLock
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import inspect, select, text

import app.main as main
from app.auth import Principal
from app.database import (AccountRecord, DatabaseManager, ProjectMembershipRecord,
    ProjectAuditEventRecord, ProjectRecord, ProjectSceneRuntimeGrantRecord)
from app.project_scenes import ProjectScenes, SceneRuntimeGrantRequest
from app.scene_parameter_digest import canonical_parameter_json, parameter_digest
import test_project_scenes as fixtures


class CompositeGrantApiTests(fixtures.SceneApiTests):
    # Reuse the API fixture and its regression tests as well as the new cases.
    def multi(self, mode="sync"):
        members = [{**self.member("helmet", target="mobile"), "memberId": "helmet-a"},
            {**self.member("helmet", 1, version="2.0.0", target="mobile"), "memberId": "helmet-b"}]
        response = self.create({**self.scene, "models": members, "plans": [{"planId": "combined",
            "name": "Combined", "inputTypes": ["image", "video"], "memberIds": ["helmet-b", "helmet-a"],
            "execution": mode, "enabled": True}]})
        self.assertEqual(201, response.status_code, response.text)
        approval = self.client.post(self.scenes + "/safety/approval", headers=self.owner,
            json={"approved": True, "expectedRevision": 1, "reason": "internal test"})
        self.assertEqual(200, approval.status_code, approval.text)
        return self.scenes + "/safety/plans/combined/runtime-grants", {
            "planId": "combined", "expectedRevision": 2, "target": "mobile", "inputType": "image",
            "clientContractVersion": 3, "supportedExecutionModes": [mode]}

    def post(self, url, body, status=200, headers=None):
        result = self.client.post(url, headers=headers or self.user, json=body)
        self.assertEqual(status, result.status_code, result.text)
        return result.json()

    def test_versioned_api_golden_projection(self):
        golden = json.loads((Path(__file__).resolve().parents[1] / "docs" /
            "project-scene-runtime-grants-v2-golden.json").read_text(encoding="utf-8"))["apiVector"]
        url, body = self.multi()
        self.assertEqual(golden["request"], body)
        response = self.post(url, golden["request"])
        projected = {key: response[key] for key in
            ("operation", "runtimeAuthorization", "runtimeGrantContractVersion")}
        projected["execution"] = response["scope"]["execution"]
        projected["members"] = [{key: member[key] for key in
            ("memberId", "modelId", "modelVersion", "artifactId", "target")}
            for member in response["scope"]["members"]]
        self.assertEqual(golden["expectedResponseProjection"], projected)

    def test_composite_sync_binds_every_member_and_rotates_once(self):
        for mode in ("sync",):
            with self.subTest(mode=mode):
                url, body = self.multi(mode)
                resolved = self.post(url.replace("runtime-grants", "resolve"), body)
                self.assertFalse(resolved["runtimeAuthorization"])
                started = self.post(url, body)
                self.assertEqual(mode, started["scope"]["execution"])
                members = started["scope"]["members"]
                self.assertEqual(["helmet-b", "helmet-a"], [m["memberId"] for m in members])
                for actual, approved in zip(members, resolved["members"]):
                    self.assertEqual(parameter_digest(approved["parameterSnapshot"]), actual["parameterSha256"])
                    self.assertEqual(approved["artifactSha256"], actual["artifactSha256"])
                rotated = self.post(url, {**body, "operation": "heartbeat", "grantToken": started["runtimeGrant"]})
                self.assertNotEqual(started["runtimeGrant"], rotated["runtimeGrant"])
                self.post(url, {**body, "operation": "renew", "grantToken": started["runtimeGrant"]}, 403)
                stop = {**body, "operation": "stop", "grantToken": rotated["runtimeGrant"]}
                self.assertFalse(self.post(url, stop)["runtimeAuthorization"])
                self.assertFalse(self.post(url, stop)["runtimeAuthorization"])

    def test_composite_async_requires_matching_client_capability(self):
        url, body = self.multi("async")
        for changes in ({"clientContractVersion": 2}, {"supportedExecutionModes": []},
                        {"supportedExecutionModes": ["sync"]}):
            self.post(url, {**body, **changes}, 409)
        first = self.post(url, body)
        self.assertEqual("async", first["scope"]["execution"])
        rotated = self.post(url, {**body, "operation": "heartbeat", "grantToken": first["runtimeGrant"]})
        self.assertEqual(first["scope"], rotated["scope"])
        self.post(url, {**body, "operation": "stop", "grantToken": rotated["runtimeGrant"]})

    def test_start_request_id_replay_cannot_mint_second_grant(self):
        url, body = self.multi()
        headers = {**self.user, "Idempotency-Key": "m39-start-once"}
        first = self.post(url, body, headers=headers)
        repeated = self.post(url, body, 409, headers=headers)
        self.assertEqual("runtime_grant_request_replayed", repeated["detail"]["code"])
        audits = self.client.get(self.project_path + "/audit", headers=self.owner).json()["events"]
        runtime_audits = [a for a in audits if a["action"].startswith("scene.runtime_grant.")]
        self.assertEqual(1, len(runtime_audits))
        self.assertNotIn(first["runtimeGrant"], json.dumps(runtime_audits))

    def test_partial_member_denial_never_issues_partial_lease(self):
        url, body = self.multi()
        for mutation in ("release", "signature", "bytes", "parameters"):
            registry = main.model_catalog._load()
            before = deepcopy(registry)
            scene = self.scene_store._memory[(self.project_id, "safety")]
            scene_before = deepcopy(scene)
            entry = next(m for m in registry["models"] if m["version"] == "2.0.0")
            if mutation == "release": entry["status"] = "REVOKED"
            if mutation == "signature": entry["signatureStatus"] = "invalid"
            if mutation == "bytes": entry["artifacts"][1]["sha256"] = "0" * 64
            if mutation == "parameters": scene["models"][1].pop("parameterSnapshot")
            main.model_catalog._save(registry)
            with self.subTest(mutation=mutation):
                result = self.client.post(url, headers=self.user, json=body)
                self.assertIn(result.status_code, (404, 409), result.text)
                self.assertEqual({}, self.scene_store._runtime_grants._leases)
            main.model_catalog._save(before)
            self.scene_store._memory[(self.project_id, "safety")] = scene_before

    def test_each_member_snapshot_change_consumes_old_token_even_after_restore(self):
        url, body = self.multi()
        for mutation in ("order", "parameters", "artifact", "version", "missing"):
            grant = self.post(url, body)
            resolve = self.scene_store.resolve_plan
            def changed(*args):
                result = resolve(*args)
                if mutation == "order": result["members"].reverse()
                if mutation == "parameters": result["members"][1]["parameterSnapshot"]["extra"] = "变更"
                if mutation == "artifact": result["members"][1]["artifacts"][0]["sha256"] = "0" * 64
                if mutation == "version": result["members"][1]["version"] = "9.0.0"
                if mutation == "missing": result["members"].pop()
                return result
            renewal = {**body, "operation": "renew", "grantToken": grant["runtimeGrant"]}
            with self.subTest(mutation=mutation), patch.object(self.scene_store, "resolve_plan", side_effect=changed):
                self.assertEqual("runtime_grant_scope_mismatch", self.post(url, renewal, 403)["detail"]["code"])
            self.post(url, renewal, 403)

    def test_cross_scope_denied_without_consuming_legitimate_token(self):
        url, body = self.multi()
        grant = self.post(url, body)["runtimeGrant"]
        renewal = {**body, "operation": "heartbeat", "grantToken": grant}
        for changes in ({"inputType": "video"}, {"target": "pc"}, {"expectedRevision": 1}):
            self.post(url, {**renewal, **changes}, 403)
        self.post(url, renewal, 403, headers=self.owner)
        self.post(url.replace(self.project_id, self.other_id), renewal, 404)
        self.post(url.replace("/combined/", "/another/"), {**renewal, "planId": "another"}, 403)
        self.post(url, renewal)

    def test_stop_after_revision_edit_and_expiry_is_idempotent(self):
        url, body = self.multi()
        grant = self.post(url, body)["runtimeGrant"]
        lease = next(iter(self.scene_store._runtime_grants._leases.values()))
        lease["expiresAt"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        edited = self.client.patch(self.scenes + "/safety", headers=self.owner,
            json={"expectedRevision": 2, "name": "review needed"})
        self.assertEqual(200, edited.status_code)
        stop = {**body, "operation": "stop", "grantToken": grant}
        self.post(url, stop)
        self.post(url, stop)
        self.post(url, {**stop, "operation": "heartbeat"}, 403)

    def test_membership_revoked_then_restored_at_http_gate_cannot_resurrect_token(self):
        url, body = self.multi()
        grant = self.post(url, body)["runtimeGrant"]
        account = self.client.get("/aiyoloapi/auth/me", headers=self.user).json()["accountId"]
        member_url = self.project_path + "/members/" + account
        disabled = self.client.patch(member_url, headers=self.owner,
            json={"expectedRevision": 1, "enabled": False})
        self.assertEqual(200, disabled.status_code, disabled.text)
        renewal = {**body, "operation": "renew", "grantToken": grant}
        self.post(url, renewal, 404)
        enabled = self.client.patch(member_url, headers=self.owner,
            json={"expectedRevision": 2, "enabled": True})
        self.assertEqual(200, enabled.status_code, enabled.text)
        self.post(url, renewal, 403)
        self.post(url, body)


class CompositeGrantPersistenceTests(fixtures.SceneSqliteTests):
    def prepare(self):
        from app.project_auth import PROJECT_USER_CAPABILITIES
        with self.db.session() as session:
            session.add(AccountRecord(account_id="runner", username="runner", password_hash="not-login",
                role="operator", platform_role="NORMAL_USER", enabled=True))
            session.flush()
            session.add(ProjectMembershipRecord(project_id="p1", account_id="runner",
                project_role="PROJECT_USER", enabled=True))
        self.context = SimpleNamespace(project_id="p1", project_role="PROJECT_USER",
            principal=Principal("runner", "runner", "operator", "NORMAL_USER"),
            capabilities=PROJECT_USER_CAPABILITIES)
        created = self.store.save("p1", "safety", self.changes, 0, creating=True)
        self.store.save("p1", "safety", {"plans": [{"planId": "combined", "name": "Combined",
            "inputTypes": ["video"], "memberIds": [m["memberId"] for m in created["models"]],
            "execution": "sync", "enabled": True}]}, 1)
        self.store.save("p1", "safety", {"approved": True}, 2, approval_reason="review")
        self.body = dict(planId="combined", expectedRevision=3, target="pc", inputType="video",
            clientContractVersion=3, supportedExecutionModes=["sync"])
        def artifacts(member):
            return {}, [{"artifactId": "server", "sha256": hashlib.sha256(member["modelId"].encode()).hexdigest(),
                         "sizeBytes": 10, "target": "pc"}]
        self.artifact_patch = patch.object(ProjectScenes, "_validated_artifacts", side_effect=artifacts)
        self.artifact_patch.start()
        self.addCleanup(self.artifact_patch.stop)

    def run_grant(self, store=None, request_id=None, **changes):
        return (store or self.store).runtime_grant("p1", "safety", "combined", "runner",
            SceneRuntimeGrantRequest(**(self.body | changes)), context=self.context, request_id=request_id)

    def test_composite_persists_reopens_and_audits_without_credentials(self):
        self.prepare()
        first = self.run_grant(request_id="persist")
        self.db.close()
        reopened = ProjectScenes(self.db, self.catalog, self.assignments)
        renewed = self.run_grant(reopened, operation="renew", grantToken=first["runtimeGrant"])
        self.assertEqual(first["scope"], renewed["scope"])
        with self.db.session() as session:
            rows = session.scalars(select(ProjectSceneRuntimeGrantRecord)).all()
            self.assertEqual(2, len(rows))
            self.assertEqual(first["scope"]["members"], rows[0].member_snapshot)
            self.assertNotIn(first["runtimeGrant"], str([r.token_digest for r in rows]))
            audit = session.scalars(select(ProjectAuditEventRecord)).all()
            self.assertNotIn(first["runtimeGrant"], json.dumps([a.change_summary for a in audit]))

    def test_revoked_membership_account_and_revision_cannot_renew_or_resurrect(self):
        self.prepare()
        for kind in ("membership", "account", "revision"):
            first = self.run_grant()
            with self.db.session() as session:
                row = session.get(ProjectMembershipRecord, ("p1", "runner")) if kind == "membership" else session.get(AccountRecord, "runner")
                if kind != "revision": row.enabled = False
            if kind == "revision": self.store.save("p1", "safety", {"name": "Changed"}, 3)
            with self.subTest(kind=kind), self.assertRaises(HTTPException):
                self.run_grant(operation="renew", grantToken=first["runtimeGrant"])
            with self.db.session() as session:
                row = session.get(ProjectMembershipRecord, ("p1", "runner")) if kind == "membership" else session.get(AccountRecord, "runner")
                if kind != "revision": row.enabled = True
            with self.assertRaises(HTTPException):
                self.run_grant(operation="renew", grantToken=first["runtimeGrant"])
            if kind == "revision":
                self.run_grant(operation="stop", grantToken=first["runtimeGrant"])
                self.run_grant(operation="stop", grantToken=first["runtimeGrant"])

    def test_failed_audit_rolls_back_new_lease_and_token_rotation(self):
        self.prepare()
        first = self.run_grant()
        with patch("app.project_scenes.audit_change", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.run_grant(operation="renew", grantToken=first["runtimeGrant"])
        with self.db.session() as session:
            rows = session.scalars(select(ProjectSceneRuntimeGrantRecord)).all()
            self.assertEqual(1, len(rows))
            self.assertIsNone(rows[0].revoked_at)
        self.run_grant(operation="heartbeat", grantToken=first["runtimeGrant"])

    def test_request_replay_persists_across_workers(self):
        self.prepare()
        self.run_grant(request_id="once")
        reopened = ProjectScenes(self.db, self.catalog, self.assignments)
        with self.assertRaises(HTTPException) as error:
            self.run_grant(reopened, request_id="once")
        self.assertEqual("runtime_grant_request_replayed", error.exception.detail["code"])
        with self.db.session() as session:
            self.assertEqual(1, len(session.scalars(select(ProjectSceneRuntimeGrantRecord)).all()))

    def test_authority_generation_change_without_intermediate_renewal_denies_old_token(self):
        self.prepare()
        for kind in ("account", "membership", "project", "recreated-membership"):
            first = self.run_grant()
            with self.db.session() as session:
                if kind == "recreated-membership":
                    row = session.get(ProjectMembershipRecord, ("p1", "runner"))
                    revision = row.revision
                    session.delete(row)
                    session.flush()
                    session.add(ProjectMembershipRecord(project_id="p1", account_id="runner",
                        project_role="PROJECT_USER", enabled=True, revision=revision,
                        created_at=datetime.now(timezone.utc) + timedelta(seconds=1)))
                else:
                    row = (session.get(AccountRecord, "runner") if kind == "account" else
                        session.get(ProjectRecord, "p1") if kind == "project" else
                        session.get(ProjectMembershipRecord, ("p1", "runner")))
                    row.revision += 2  # disable/re-enable completed before this request
            with self.subTest(kind=kind), self.assertRaises(HTTPException) as error:
                self.run_grant(operation="renew", grantToken=first["runtimeGrant"])
            self.assertEqual("runtime_grant_scope_mismatch", error.exception.detail["code"])
            self.run_grant(operation="stop", grantToken=first["runtimeGrant"])


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL")
class CompositeGrantPostgresTests(CompositeGrantPersistenceTests):
    use_postgresql = True

    def test_two_workers_cannot_renew_same_composite_token(self):
        self.prepare()
        first = self.run_grant()
        stores = [ProjectScenes(self.db, self.catalog, self.assignments) for _ in range(2)]
        for store in stores: store._lock = RLock()
        barrier = Barrier(2)
        def worker(store):
            barrier.wait(timeout=10)
            try:
                return self.run_grant(store, operation="renew", grantToken=first["runtimeGrant"])["runtimeAuthorization"]
            except HTTPException: return False
        # Remove shared process locks: only database locks may arbitrate workers.
        with patch("app.model_catalog._mutation_lock", nullcontext()), \
             patch("app.project_management._mutation_lock", nullcontext()), \
             ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual([True, False], list(executor.map(worker, stores)))

    def test_revoke_committed_while_waiting_for_project_lock_wins(self):
        self.prepare()
        first = self.run_grant()
        from app.project_business import lock_project
        started = Event()
        def renew():
            started.set()
            try:
                self.run_grant(operation="renew", grantToken=first["runtimeGrant"])
                return "issued"
            except HTTPException: return "denied"
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.db.session() as session:
                lock_project(session, "p1")
                future = executor.submit(renew)
                self.assertTrue(started.wait(5))
                session.get(ProjectMembershipRecord, ("p1", "runner")).enabled = False
            self.assertEqual("denied", future.result(timeout=15))

    def test_revision_committed_while_waiting_for_project_lock_wins(self):
        self.prepare()
        first = self.run_grant()
        started = Event()
        def renew():
            started.set()
            try:
                self.run_grant(operation="heartbeat", grantToken=first["runtimeGrant"])
                return "issued"
            except HTTPException: return "denied"
        from app.project_business import lock_project
        from app.database import ProjectSceneRecord
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.db.session() as session:
                lock_project(session, "p1")
                future = executor.submit(renew)
                self.assertTrue(started.wait(5))
                session.get(ProjectSceneRecord, ("p1", "safety")).revision += 1
            self.assertEqual("denied", future.result(timeout=15))
        # Restoring the old database revision cannot resurrect the consumed token.
        with self.db.session() as session:
            session.get(ProjectSceneRecord, ("p1", "safety")).revision -= 1
        with self.assertRaises(HTTPException):
            self.run_grant(operation="renew", grantToken=first["runtimeGrant"])


class ParameterCanonicalIdentityTests(unittest.TestCase):
    def test_published_parameter_golden(self):
        golden = json.loads((Path(__file__).resolve().parents[1] / "docs" /
            "project-scene-runtime-grants-v2-golden.json").read_text(encoding="utf-8"),
            parse_float=Decimal)
        self.assertEqual(golden["canonicalUtf8Text"], canonical_parameter_json(golden["parameterSnapshot"]))
        self.assertEqual(golden["sha256"], parameter_digest(golden["parameterSnapshot"]))

    def test_android_canonical_vector_is_lossless_unicode_decimal_and_ordered(self):
        snapshot = {"中文": "帽\n", "z": Decimal("1E-7"), "a": [-0.0, True, None,
            Decimal("123456789012345678901234567890.00100")]}
        expected = '{"a":[0,true,null,123456789012345678901234567890.001],"z":0.0000001,"中文":"帽\\n"}'
        self.assertEqual(expected, canonical_parameter_json(snapshot))
        self.assertEqual(hashlib.sha256(expected.encode()).hexdigest(), parameter_digest(snapshot))
        for invalid in (float("nan"), float("inf"), "\ud800"):
            with self.assertRaises((ValueError, UnicodeError)):
                parameter_digest({"invalid": invalid})


class CompositeGrantMigrationTests(unittest.TestCase):
    def exercise(self, url):
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(config, "20261021_20")
        db = DatabaseManager(url)
        try:
            with db.session() as session:
                session.add(ProjectRecord(project_id="m39-old", project_code="m39-old", display_name="Old"))
                session.add(AccountRecord(account_id="old", username="old", password_hash="not-login",
                    role="operator", platform_role="NORMAL_USER", enabled=True))
                session.flush()
                session.execute(text("INSERT INTO project_scenes "
                    "(project_id,scene_id,display_name,input_types,enabled,approved,revision) "
                    "VALUES ('m39-old','s','S','[\"image\"]',true,true,1)"))
                session.execute(text("INSERT INTO project_scene_members "
                    "(project_id,scene_id,position,member_id,model_id,model_version,target,execution,input_types) "
                    "VALUES ('m39-old','s',0,'m','helmet','1.0.0','mobile','single','[\"image\"]')"))
                session.execute(text("INSERT INTO project_scene_runtime_grants "
                    "(grant_id,token_digest,project_id,scene_id,account_id,scene_revision,plan_id,member_id,"
                    "input_type,target,client_contract_version,supported_execution_modes,model_id,model_version,"
                    "artifact_id,artifact_sha256,parameter_revision,expires_at) VALUES "
                    "('old',:digest,'m39-old','s','old',1,'p','m','image','mobile',2,'[]','helmet','1.0.0',"
                    "'android',:artifact,0,:expiry)"), {"digest": "a" * 64, "artifact": "b" * 64,
                    "expiry": datetime.now(timezone.utc) + timedelta(minutes=2)})
            command.upgrade(config, "20261022_21")
            command.upgrade(config, "20261022_21")
            with db.session() as session:
                old = session.get(ProjectSceneRuntimeGrantRecord, "old")
                self.assertEqual(("single", [], {}), (old.execution_mode, old.member_snapshot, old.authority_snapshot))
                self.assertEqual("a" * 64, old.token_digest)
                self.assertIsNotNone(old.revoked_at)  # require fresh start after upgrade
                session.execute(text("DELETE FROM project_scene_members WHERE project_id='m39-old'"))
            with db.session() as session:
                self.assertIsNotNone(session.get(ProjectSceneRuntimeGrantRecord, "old"))
            self.assertNotIn("fk_scene_runtime_grants_scene_member",
                [f["name"] for f in inspect(db.engine).get_foreign_keys("project_scene_runtime_grants")])
            with self.assertRaisesRegex(RuntimeError, "grant records exist"):
                command.downgrade(config, "20261021_20")
            with db.session() as session:
                self.assertEqual("20261022_21", session.scalar(text("SELECT version_num FROM alembic_version")))
                session.execute(text("DELETE FROM project_scene_runtime_grants"))
            command.downgrade(config, "20261021_20")
            command.upgrade(config, "head")
            db.verify_schema()
        finally:
            db.close()

    def test_sqlite_legacy_token_migration_and_downgrade_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            self.exercise("sqlite:///" + (Path(directory) / "old.db").as_posix())

    @unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL")
    def test_postgres_legacy_token_migration_and_downgrade_guard(self):
        from postgresql_support import isolated_postgresql_url
        with isolated_postgresql_url("m39_migrate", revision="20261021_20") as url:
            self.exercise(url)
