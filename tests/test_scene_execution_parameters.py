"""Exact scene authority, not a legacy model assignment or a guessed revision."""
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier, RLock
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import select, text

import app.main as main
from app.database import (AccountRecord, DatabaseManager, ProjectRecord, ProjectSceneRecord, ProjectSceneMemberRecord,
                          ProjectSceneRuntimeGrantRecord)
from app.project_scenes import ProjectScenes
from test_project_scenes import SceneApiTests, SceneSqliteTests


class SceneExecutionApiTests(SceneApiTests):
    def test_project_and_scene_parameter_writes_are_retired(self):
        scene = self.mobile_scene()
        member = scene["models"][0]
        url = f"{self.scenes}/safety/members/{member['memberId']}/parameter-profile?sceneRevision=2"
        profile = self.client.get(url, headers=self.owner).json()
        body = {key: profile[key] for key in ("schemaVersion", "detection", "alertRules")} | {"expectedRevision": 0}
        before = main.project_scenes.get(self.project_id, "safety")
        self.assertEqual(410, self.client.put(url, headers=self.owner, json=body).status_code)
        project_url = self.project_path + "/models/helmet/parameters?platform=android&version=1.0.0"
        self.assertEqual(410, self.client.put(project_url, headers=self.owner, json=body).status_code)
        self.assertEqual(410, self.client.delete(project_url + "&expectedRevision=0", headers=self.owner).status_code)
        self.assertEqual(before, main.project_scenes.get(self.project_id, "safety"))
        self.assertEqual("platform", self.client.get(project_url, headers=self.user).json()["source"])


    def test_platform_publication_preserves_running_grant_and_updates_new_start(self):
        scene = self.mobile_scene()
        runtime = self.scenes + "/safety/plans/default/runtime-grants"
        payload = {"planId": "default", "expectedRevision": 2, "target": "mobile", "inputType": "image", "clientContractVersion": 2}
        started = self.client.post(runtime, headers=self.user, json=payload)
        self.assertEqual(200, started.status_code, started.text)
        model = main.model_catalog.get("helmet", "1.0.0")
        store = main.model_parameter_store
        profile = store.get(model, "android")
        profile["alertRules"][0]["enabled"] = False
        store.save(model, "android", profile, "admin", 0)
        store.publish(model, "android", "admin", 1, 0)
        heartbeat = self.client.post(runtime, headers=self.user,
            json={**payload, "operation": "heartbeat", "grantToken": started.json()["runtimeGrant"]})
        self.assertEqual(200, heartbeat.status_code, heartbeat.text)
        self.assertEqual(started.json()["scope"]["members"], heartbeat.json()["scope"]["members"])
        fresh = self.client.post(runtime, headers=self.user, json=payload).json()
        self.assertEqual(1, fresh["scope"]["members"][0]["parameterRevision"])
        self.assertNotEqual(started.json()["scope"]["members"][0]["parameterSha256"], fresh["scope"]["members"][0]["parameterSha256"])
        resolved = self.client.post(runtime.replace("runtime-grants", "resolve"), headers=self.user, json=payload).json()
        self.assertFalse(resolved["members"][0]["parameterSnapshot"]["alertRules"][0]["enabled"])
        self.assertEqual(scene["models"][0]["artifacts"][0]["sha256"], resolved["members"][0]["artifacts"][0]["sha256"])


    def test_scene_profile_rejects_user_foreign_project_member_stale_and_injected_identity(self):
        scene = self.mobile_scene()
        member = scene['models'][0]
        url = f"{self.scenes}/safety/members/{member['memberId']}/parameter-profile?sceneRevision=2"
        profile = self.client.get(url,headers=self.owner).json()
        body = {key:profile[key] for key in ('schemaVersion','detection','alertRules')} | {'expectedRevision':0}
        for method in ('get','put'):
            kwargs={'json':body} if method=='put' else {}
            call=getattr(self.client,method)
            self.assertEqual(403,call(url,headers=self.user,**kwargs).status_code)
            self.assertEqual(404,call(url.replace(self.project_id,self.other_id),headers=self.owner,**kwargs).status_code)
            self.assertEqual(410 if method == "put" else 404,call(url.replace(member['memberId'],'missing'),headers=self.owner,**kwargs).status_code)
            self.assertEqual(410 if method == 'put' else 409,call(url.replace('sceneRevision=2','sceneRevision=1'),headers=self.owner,**kwargs).status_code)
        self.assertEqual(422,self.client.put(url,headers=self.owner,json={**body,'modelId':'secret'}).status_code)
        registry=main.model_catalog._load();registry['models'][0]['status']='REVOKED';main.model_catalog._save(registry)
        self.assertEqual(410,self.client.put(url,headers=self.owner,json=body).status_code)

    def approve(self, expected=1, approved=True):
        response = self.client.post(self.scenes + "/safety/approval", headers=self.owner,
            json={"approved": approved, "expectedRevision": expected, "reason": "parameter review"})
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def mobile_scene(self):
        self.assertEqual(201, self.create({**self.scene, "models": [self.member("helmet", target="mobile")]}).status_code)
        self.approve()
        return self.client.get(self.scenes + "/safety?target=mobile", headers=self.user).json()

    def test_frozen_exact_parameters_catalog_and_revision_download_from_inventory(self):
        scene = self.mobile_scene()
        member = scene["models"][0]
        self.assertTrue(member["executionReady"])
        self.assertEqual(("android", 0), (member["parameterPlatform"], member["parameterRevision"]))
        profile = self.client.get(member["parameterUrl"], headers=self.user)
        self.assertEqual(200, profile.status_code, profile.text)
        self.assertEqual((self.project_id, "safety", 2, "helmet", "1.0.0", "android"), tuple(
            profile.json()[key] for key in ("projectId", "sceneId", "sceneRevision", "modelId", "modelVersion", "platform")))
        self.assertNotIn("audit", profile.json())
        self.assertNotIn("updatedBy", profile.json())
        self.assertEqual((2, "platform"), tuple(profile.json()[key] for key in ("schemaVersion", "source")))
        release = member["executionModel"]
        self.assertEqual(("helmet", "1.0.0", "PUBLISHED"), tuple(release[key] for key in ("modelId", "version", "status")))
        self.assertNotIn("downloadUrl", release)
        for artifact in release["artifacts"]:
            self.assertIn("?expectedRevision=2", artifact["url"])
            self.assertEqual("mobile", artifact["target"])
            self.assertNotIn("versionedUrl", artifact)
            self.assertEqual(200, self.client.get(artifact["url"], headers=self.user).status_code)
            self.assertEqual(409, self.client.get(artifact["url"].replace("=2", "=1"), headers=self.user).status_code)
        self.assertEqual(5, len(main.project_model_assignments.list(self.project_id)))
        self.assertEqual(200, self.client.get(self.project_path +
            "/models/helmet/versions/1.0.0/artifacts/android/download", headers=self.user).status_code)
        resolved = self.client.post(self.scenes + "/safety/resolve", headers=self.user,
            json={"expectedRevision": 2, "target": "mobile", "inputType": "image"})
        self.assertEqual(200, resolved.status_code)
        self.assertEqual(release, resolved.json()["model"]["executionModel"])

    def test_runtime_grant_is_short_lived_account_scoped_and_revalidated(self):
        self.mobile_scene()
        url = self.scenes + "/safety/plans/default/runtime-grants"
        payload = {"planId": "default", "expectedRevision": 2, "target": "mobile",
                   "inputType": "image", "clientContractVersion": 2}
        resolved = self.client.post(self.scenes + "/safety/plans/default/resolve",
                                    headers=self.user, json=payload)
        self.assertEqual(200, resolved.status_code, resolved.text)
        self.assertFalse(resolved.json()["runtimeAuthorization"])
        started = self.client.post(url, headers=self.user, json=payload)
        self.assertEqual(200, started.status_code, started.text)
        grant = started.json()
        self.assertTrue(grant["runtimeAuthorization"])
        self.assertEqual("start", grant["operation"])
        ttl = (datetime.fromisoformat(grant["expiresAt"]) - datetime.now(timezone.utc)).total_seconds()
        self.assertGreater(ttl, 115)
        self.assertLessEqual(ttl, 120)
        self.assertNotEqual(grant["runtimeGrant"], grant["scope"].get("runtimeGrant"))
        self.assertEqual((self.project_id, "safety", 2, "default", "mobile", "image"), tuple(
            grant["scope"][key] for key in ("projectId", "sceneId", "expectedRevision", "planId", "target", "inputType")))

        heartbeat = self.client.post(url, headers=self.user,
            json={**payload, "operation": "heartbeat", "grantToken": grant["runtimeGrant"]})
        self.assertEqual(200, heartbeat.status_code, heartbeat.text)
        self.assertNotEqual(grant["runtimeGrant"], heartbeat.json()["runtimeGrant"])
        self.assertEqual(403, self.client.post(url, headers=self.owner,
            json={**payload, "operation": "heartbeat", "grantToken": heartbeat.json()["runtimeGrant"]}).status_code)

        stopped = self.client.post(url, headers=self.user,
            json={**payload, "operation": "stop", "grantToken": heartbeat.json()["runtimeGrant"]})
        self.assertEqual(200, stopped.status_code, stopped.text)
        self.assertFalse(stopped.json()["runtimeAuthorization"])
        self.assertEqual(403, self.client.post(url, headers=self.user,
            json={**payload, "operation": "heartbeat", "grantToken": heartbeat.json()["runtimeGrant"]}).status_code)

    def test_runtime_grant_renewal_fails_after_scene_revision_changes(self):
        self.mobile_scene()
        url = self.scenes + "/safety/plans/default/runtime-grants"
        payload = {"planId": "default", "expectedRevision": 2, "target": "mobile", "inputType": "image"}
        grant = self.client.post(url, headers=self.user, json=payload).json()["runtimeGrant"]
        edited = self.client.patch(self.scenes + "/safety", headers=self.owner,
            json={"expectedRevision": 2, "name": "changed"})
        self.assertEqual(200, edited.status_code, edited.text)
        renewed = self.client.post(url, headers=self.user,
            json={**payload, "operation": "renew", "grantToken": grant})
        self.assertIn(renewed.status_code, (404, 409))

    def test_publication_updates_parameters_without_changing_scene_or_weight_urls(self):
        scene = self.mobile_scene()
        member = scene["models"][0]
        before = self.client.get(member["parameterUrl"], headers=self.user).json()
        model = main.model_catalog.get("helmet", "1.0.0")
        store = main.model_parameter_store
        draft = store.get(model, "android")
        draft["detection"]["confidenceThreshold"] = .22
        store.save(model, "android", draft, "admin", 0)
        self.assertEqual(before, self.client.get(member["parameterUrl"], headers=self.user).json())
        store.publish(model, "android", "admin", 1, 0)
        after = self.client.get(member["parameterUrl"], headers=self.user).json()
        self.assertEqual((1, .22), (after["revision"], after["detection"]["confidenceThreshold"]))
        self.assertEqual(200, self.client.get(member["executionModel"]["artifacts"][0]["url"], headers=self.user).status_code)
        self.assertEqual(2, main.project_scenes.get(self.project_id, "safety")["revision"])
        self.assertEqual(0, scene["models"][0]["parameterSnapshot"]["revision"])


    def test_edit_revoke_cross_project_target_version_and_member_checks(self):
        scene = self.mobile_scene()
        member = scene["models"][0]
        params = member["parameterUrl"]
        download = member["executionModel"]["artifacts"][0]["url"]
        for url in (params.replace(self.project_id, self.other_id), params.replace("target=mobile", "target=pc"),
                    params.replace("versions/1.0.0", "versions/2.0.0")):
            self.assertEqual(404, self.client.get(url, headers=self.user).status_code)
        self.approve(2, False)
        for url in (params, download):
            self.assertEqual(404, self.client.get(url, headers=self.user).status_code)
        self.assertNotIn("parameterSnapshot", self.scene_store.get(self.project_id, "safety")["models"][0])
        self.approve(3)
        edited = self.client.patch(self.scenes + "/safety", headers=self.owner,
            json={"expectedRevision": 4, "name": "needs review"})
        self.assertEqual(200, edited.status_code)
        self.assertNotIn("parameterSnapshot", edited.json()["models"][0])
        self.assertFalse(edited.json()["approved"])
        self.approve(5)
        new_member = self.client.get(self.scenes + "/safety", headers=self.user).json()["models"][0]
        account_id = self.client.get("/aiyoloapi/auth/me", headers=self.user).json()["accountId"]
        membership = next(m for m in self.client.get(self.project_path + "/members", headers=self.owner).json()["members"]
                          if m["accountId"] == account_id)
        self.assertEqual(204, self.client.delete(self.project_path + "/members/" + account_id, headers=self.owner,
            params={"expectedRevision": membership["revision"]}).status_code)
        for url in (new_member["parameterUrl"], new_member["executionModel"]["artifacts"][0]["url"]):
            self.assertEqual(404, self.client.get(url, headers=self.user).status_code)

    def test_legacy_scene_snapshot_is_not_authority_and_client_cannot_inject_one(self):
        scene = self.mobile_scene()
        self.scene_store._memory[(self.project_id, "safety")]["models"][0].pop("parameterSnapshot")
        visible = self.client.get(self.scenes + "/safety", headers=self.user).json()
        self.assertTrue(visible["models"][0]["executionReady"])
        self.assertEqual("platform", visible["models"][0]["parameterSnapshot"]["source"])
        injected = {**self.scene, "sceneId": "injection", "models": [
            {**self.member("helmet"), "parameterSnapshot": scene["models"][0]["parameterSnapshot"]}]}
        self.assertEqual(422, self.create(injected).status_code)
        from app.model_parameters import ModelParameterError
        with patch.object(main.model_parameter_store, "published", side_effect=ModelParameterError("platform_parameters_unpublished", "unpublished")):
            response = self.client.post(self.scenes + "/safety/resolve", headers=self.user,
                json={"expectedRevision": 2, "target": "mobile", "inputType": "image"})
            self.assertIn(response.status_code, (404, 409))


    def test_model_revoke_and_multi_model_remain_fail_closed(self):
        scene = self.mobile_scene()
        member = scene["models"][0]
        result = self.client.put(self.scenes + "/safety/models", headers=self.owner, json={
            "expectedRevision": 2, "models": [self.member("helmet", target="mobile", execution="sync"),
                self.member("helmet", 1, version="2.0.0", target="mobile", execution="async")]})
        self.assertEqual(200, result.status_code)
        self.approve(3)
        multi = self.client.post(self.scenes + "/safety/resolve", headers=self.user,
            json={"expectedRevision": 4, "target": "mobile", "inputType": "image"})
        self.assertEqual("execution_mode_not_supported", multi.json()["detail"]["code"])
        registry = main.model_catalog._load()
        registry["models"][0]["status"] = "REVOKED"
        main.model_catalog._save(registry)
        for url in (member["parameterUrl"], member["executionModel"]["artifacts"][0]["url"]):
            self.assertEqual(404, self.client.get(url, headers=self.user).status_code)


class SceneParameterSqliteTests(SceneSqliteTests):
    def test_platform_publication_survives_reopen_without_mutating_scene_history(self):
        self.store.save("p1", "safety", self.changes, 0, creating=True)
        approved = self.store.save("p1", "safety", {"approved": True}, 1, approval_reason="review")
        model = self.catalog.get("helmet", "1.0.0")
        parameters = self.assignments.parameters
        draft = parameters.get(model, "server")
        draft["alertRules"][0]["enabled"] = False
        parameters.save(model, "server", draft, "admin", 0)
        parameters.publish(model, "server", "admin", 1, 0)
        self.db.close()
        reopened = ProjectScenes(self.db, self.catalog, self.assignments)
        self.assertEqual(approved, reopened.get("p1", "safety"))
        profile = reopened.reviewed_parameters(approved, approved["models"][0])
        self.assertEqual(1, profile["revision"])
        self.assertFalse(profile["alertRules"][0]["enabled"])


    def test_runtime_grant_digest_persists_and_is_atomically_consumed(self):
        from app.project_scenes import SceneRuntimeGrant
        scene = self.store.save("p1", "safety", self.changes, 0, creating=True)
        member = scene["models"][0]
        with self.db.session() as session:
            session.add(AccountRecord(account_id="runtime-user", username="runtime-user",
                password_hash="not-a-login", role="operator", platform_role="NORMAL_USER", enabled=True))
        scope = {"accountId": "runtime-user", "projectId": "p1", "sceneId": "safety",
            "expectedRevision": scene["revision"], "planId": "single", "memberId": member["memberId"],
            "inputType": "video", "target": member["target"], "clientContractVersion": 2,
            "supportedExecutionModes": [], "modelId": member["modelId"],
            "modelVersion": member["version"], "artifactId": "artifact", "artifactSha256": "a" * 64,
            "parameterRevision": 0}
        manager = SceneRuntimeGrant(self.db)
        token, _ = manager.issue(scope)
        reopened_manager = SceneRuntimeGrant(self.db)
        lease = reopened_manager.get(token, {key: scope[key] for key in (
            "accountId", "projectId", "sceneId", "expectedRevision", "planId", "inputType",
            "target", "clientContractVersion", "supportedExecutionModes")})
        self.assertEqual(member["memberId"], lease["memberId"])
        with self.db.session() as session:
            row = session.scalar(select(ProjectSceneRuntimeGrantRecord))
            self.assertNotEqual(token, row.token_digest)
            self.assertIsNotNone(row.revoked_at)
        with self.assertRaises(HTTPException):
            reopened_manager.get(token)

    def test_postgres_runtime_grant_cannot_be_consumed_twice_concurrently(self):
        if self.db.backend != "postgresql":
            self.skipTest("requires PostgreSQL row-level locking")
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from app.project_scenes import SceneRuntimeGrant
        scene = self.store.save("p1", "safety", self.changes, 0, creating=True)
        member = scene["models"][0]
        with self.db.session() as session:
            session.add(AccountRecord(account_id="runtime-user", username="runtime-user",
                password_hash="not-a-login", role="operator", platform_role="NORMAL_USER", enabled=True))
        scope = {"accountId": "runtime-user", "projectId": "p1", "sceneId": "safety",
            "expectedRevision": scene["revision"], "planId": "single", "memberId": member["memberId"],
            "inputType": "video", "target": member["target"], "clientContractVersion": 2,
            "supportedExecutionModes": [], "modelId": member["modelId"],
            "modelVersion": member["version"], "artifactId": "artifact", "artifactSha256": "b" * 64,
            "parameterRevision": 0}
        manager = SceneRuntimeGrant(self.db)
        token, _ = manager.issue(scope)
        expected = {key: scope[key] for key in (
            "accountId", "projectId", "sceneId", "expectedRevision", "planId", "inputType",
            "target", "clientContractVersion", "supportedExecutionModes")}
        barrier = Barrier(2)

        def consume(_):
            barrier.wait()
            try:
                manager.get(token, expected)
                return "consumed"
            except HTTPException:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(consume, range(2)))
        self.assertEqual(["consumed", "rejected"], sorted(outcomes))

    def test_project_parameter_writer_rejected_even_with_internal_context(self):
        from app.model_parameters import ModelParameterError
        model = self.catalog.get("helmet", "1.0.0")
        parameters = self.assignments.parameters
        before = parameters.get(model, "server", "p1")
        with self.assertRaises(ModelParameterError):
            parameters.save(model, "server", before, "owner", 0, "p1")
        self.assertEqual(before, parameters.get(model, "server", "p1"))


    def test_approved_multimember_plan_parameter_sources_persist_after_reopen(self):
        created = self.store.save("p1", "safety", self.changes, 0, creating=True)
        member_ids = [member["memberId"] for member in created["models"]]
        planned = self.store.save("p1", "safety", {"plans": [
            {"planId": "combined", "name": "Combined", "inputTypes": ["video"],
             "memberIds": member_ids, "execution": "sync", "enabled": True}]}, 1)
        approved = self.store.save("p1", "safety", {"approved": True}, planned["revision"], approval_reason="review")
        plan = approved["plans"][0]
        self.assertEqual(set(member_ids), {source["memberId"] for source in plan["parameterSources"]})
        self.db.close()

        reopened = ProjectScenes(self.db, self.catalog, self.assignments)
        loaded = reopened.get("p1", "safety")
        persisted_plan = loaded["plans"][0]
        self.assertEqual(plan["parameterSources"], persisted_plan["parameterSources"])
        for source in persisted_plan["parameterSources"]:
            snapshot = source["parameterSnapshot"]
            member = next(item for item in loaded["models"] if item["memberId"] == source["memberId"])
            self.assertEqual(("p1", member["modelId"], "1.0.0", "server"),
                             (snapshot["projectId"], snapshot["modelId"],
                              snapshot["modelVersion"], snapshot["platform"]))
            self.assertEqual(member["parameterSnapshot"], snapshot)

    def test_snapshot_persists_reopens_does_not_drift_and_audit_rollback(self):
        self.store.save("p1", "safety", self.changes, 0, creating=True)
        approved = self.store.save("p1", "safety", {"approved": True}, 1, approval_reason="review")
        frozen = approved["models"][0]["parameterSnapshot"]
        self.assertEqual(("p1", "helmet", "1.0.0", "server", 0), tuple(
            frozen[key] for key in ("projectId", "modelId", "modelVersion", "platform", "revision")))
        self.db.close()
        self.assertEqual(approved, self.store.get("p1", "safety"))
        with patch("app.project_scenes.audit_change", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.store.save("p1", "safety", {"approved": False}, 2, approval_reason="revoke")
        self.assertEqual(approved, self.store.get("p1", "safety"))
        self.store.save("p1", "safety", {"approved": False}, 2, approval_reason="revoke")
        self.assertNotIn("parameterSnapshot", self.store.get("p1", "safety")["models"][0])


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL schema")
class SceneParameterPostgresTests(SceneParameterSqliteTests):
    use_postgresql = True

    def test_concurrent_parameter_edit_does_not_change_inventory_snapshot_approval(self):
        self.store.save("p1", "safety", self.changes, 0, creating=True)
        model = self.catalog.get("helmet", "1.0.0")
        from app.model_parameters import ModelParameterStore
        # Independent store locks simulate two processes; project rows serialize the writers.
        writer = ModelParameterStore(Path(self.temp.name) / "params2.json", self.db)
        writer._import_legacy_once()
        initial = writer.get(model, "server", "p1")
        changed = deepcopy(initial)
        changed["detection"]["confidenceThreshold"] = 0.21
        barrier = Barrier(2)
        def edit():
            barrier.wait(timeout=10)
            return writer.save(model, "server", changed, "test", 0)
        def approve():
            barrier.wait(timeout=10)
            return self.store.save("p1", "safety", {"approved": True}, 1, approval_reason="review")
        with ThreadPoolExecutor(max_workers=2) as executor:
            edit_future, approval_future = executor.submit(edit), executor.submit(approve)
            edit_future.result(timeout=30)
            snapshot = approval_future.result(timeout=30)["models"][0]["parameterSnapshot"]
        self.assertEqual(0, snapshot["revision"])
        self.assertEqual(initial["detection"], snapshot["detection"])

    def test_concurrent_inherited_platform_edit_does_not_change_inventory_snapshot(self):
        self.store.save("p1", "safety", self.changes, 0, creating=True)
        model = self.catalog.get("helmet", "1.0.0")
        from app.model_parameters import ModelParameterStore
        writer = ModelParameterStore(Path(self.temp.name) / "platform-params.json", self.db)
        writer._import_legacy_once()
        initial = writer.get(model, "server")
        changed = deepcopy(initial)
        changed["detection"]["confidenceThreshold"] = 0.23
        barrier = Barrier(2)
        def edit():
            barrier.wait(timeout=10)
            return writer.save(model, "server", changed, "test", 0)
        def approve():
            barrier.wait(timeout=10)
            return self.store.save("p1", "safety", {"approved": True}, 1, approval_reason="review")
        with ThreadPoolExecutor(max_workers=2) as executor:
            edit_future, approval_future = executor.submit(edit), executor.submit(approve)
            edit_future.result(timeout=30)
            snapshot = approval_future.result(timeout=30)["models"][0]["parameterSnapshot"]
        self.assertEqual(0, snapshot["revision"])
        self.assertNotIn("inheritedRevision", snapshot)
        self.assertEqual(initial["detection"], snapshot["detection"])


class SceneParameterMigrationTests(unittest.TestCase):
    def exercise_migration(self, url):
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(config, "20261020_16")
        db = DatabaseManager(url)
        try:
            with db.session() as session:
                session.add(ProjectRecord(project_id="snapshot-migration", project_code="snapshot-migration", display_name="test"))
                session.flush()
                session.execute(text("INSERT INTO project_scenes "
                    "(project_id,scene_id,display_name,input_types,enabled,approved,revision) "
                    "VALUES ('snapshot-migration','old','old',:types,:enabled,:approved,5)"),
                    {"types": '["image"]', "enabled": True, "approved": True})
                session.execute(text("INSERT INTO project_scene_members "
                    "(project_id,scene_id,position,model_id,model_version,target,execution) "
                    "VALUES ('snapshot-migration','old',0,'helmet','1.0.0','mobile','single')"))
            # Schema verification now checks later scene-suite tables before
            # reaching the parameter_snapshot column guard.
            with self.assertRaisesRegex(RuntimeError, "database schema is not initialized"):
                db.verify_schema()
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            with db.session() as session:
                old = session.get(ProjectSceneRecord, ("snapshot-migration", "old"))
                member = session.get(ProjectSceneMemberRecord, ("snapshot-migration", "old", 0))
                self.assertIsNone(old)
                self.assertIsNone(member)
        finally:
            db.close()

    def test_sqlite_migration_preserves_old_approval_without_granting_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            self.exercise_migration(f"sqlite:///{(Path(directory) / 'migration.db').as_posix()}")

    @unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL schema")
    def test_postgres_migration(self):
        from postgresql_support import isolated_postgresql_url
        with isolated_postgresql_url("m36_snapshot", revision="20261020_16") as url:
            self.exercise_migration(url)
