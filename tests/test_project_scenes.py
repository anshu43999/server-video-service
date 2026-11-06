import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import select

import app.main as main
from app.database import (Base, DatabaseManager, ProjectRecord, ProjectSceneRecord, ProjectSceneMemberRecord,
                          ProjectModelAssignmentRecord)
from app.project_scenes import ProjectScenes
from app.project_management import memory_audits_for_tests
from test_project_model_assignments import ModelApiFixture


class SceneApiTests(ModelApiFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.assignments = self.project_path + "/model-assignments"
        self.body = {"modelId": "helmet", "modelVersion": "1.0.0", "target": "pc",
                     "parameterRevision": 0, "enabled": True, "expectedRevision": 0}
        self.project_models = {}
        inventory = (("helmet", "1.0.0", "pc"), ("helmet", "2.0.0", "pc"),
                     ("secret", "1.0.0", "pc"), ("helmet", "1.0.0", "mobile"),
                     ("helmet", "2.0.0", "mobile"))
        for model_id, version, target in inventory:
            response = self._assign({**self.body, "modelId": model_id, "modelVersion": version, "target": target})
            self.assertEqual(200, response.status_code, response.text)
            self.project_models[(model_id, version, target)] = response.json()["projectModelId"]
        other_assignment = self.client.put(f"/aiyoloapi/projects/{self.other_id}/model-assignments", headers=self.headers,
            json=self.body)
        self.assertEqual(200, other_assignment.status_code, other_assignment.text)
        self.other_project_model_id = other_assignment.json()["projectModelId"]
        self.scene_store = ProjectScenes(None, main.model_catalog, main.project_model_assignments)
        self.patches.enter_context(patch.object(main, "project_scenes", self.scene_store))
        self.scenes = self.project_path + "/scenes"
        self.scene = {"sceneId": "safety", "name": "现场安全", "inputTypes": ["image", "video"],
                      "expectedRevision": 0, "models": [self.member("helmet")]}

    def member(self, model_id, position=0, version="1.0.0", target="pc", execution="single", project_model_id=None):
        return {"projectModelId": project_model_id or self.project_models[(model_id, version, target)],
                "position": position, "execution": execution}

    def create(self, body=None, headers=None):
        return self.client.post(self.scenes, json=body or self.scene, headers=headers or self.owner)

    def test_create_multiple_scenes_exact_members_order_edit_disable_and_audit(self):
        body = {**self.scene, "models": [self.member("secret", 1, execution="async"), self.member("helmet")]}
        result = self.create(body)
        self.assertEqual(201, result.status_code, result.text)
        self.assertEqual(["helmet", "secret"], [m["modelId"] for m in result.json()["models"]])
        self.assertFalse(result.json()["approved"])
        self.assertEqual(201, self.create({**self.scene, "sceneId": "entrance"}).status_code)
        self.assertEqual(2, len(self.client.get(self.scenes, headers=self.owner).json()["scenes"]))
        path = self.scenes + "/safety"
        updated = self.client.put(path + "/models", headers=self.owner, json={"expectedRevision": 1,
            "models": [self.member("helmet", version="2.0.0") ]})
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual((2, "2.0.0"), (updated.json()["revision"], updated.json()["models"][0]["version"]))
        renamed = self.client.patch(path, headers=self.owner, json={"expectedRevision": 2, "name": "新场景", "inputTypes": ["video"]})
        self.assertEqual(200, renamed.status_code)
        disabled = self.client.patch(path, headers=self.owner, json={"expectedRevision": 3, "enabled": False})
        self.assertEqual(4, disabled.json()["revision"])
        self.assertFalse(self.client.get(path, headers=self.owner).json()["enabled"])
        audits = [a for a in memory_audits_for_tests()["project"] if a["action"].startswith("scene.")]
        self.assertEqual(5, len(audits))
        self.assertEqual(4, audits[-1]["newRevision"])
        self.assertEqual(5, len(main.project_model_assignments.list(self.project_id)))
        self.assertFalse(main.streams)

    def test_permissions_project_isolation_and_same_id(self):
        self.assertEqual(403, self.create(headers=self.user).status_code)
        self.assertEqual([], self.client.get(self.scenes, headers=self.user).json()["scenes"])
        other = f"/aiyoloapi/projects/{self.other_id}/scenes"
        self.assertEqual(404, self.client.post(other, headers=self.owner, json=self.scene).status_code)
        self.assertEqual(201, self.create().status_code)
        other_scene = {**self.scene, "name": "Other",
                       "models": [self.member("helmet", project_model_id=self.other_project_model_id)]}
        self.assertEqual(201, self.client.post(other, headers=self.headers, json=other_scene).status_code)
        self.assertEqual("Other", self.client.get(other + "/safety", headers=self.headers).json()["name"])
        self.assertEqual("现场安全", self.client.get(self.scenes + "/safety", headers=self.owner).json()["name"])
        self.assertEqual(404, self.client.get(self.scenes + "/missing", headers=self.owner).status_code)

    def test_approved_mixed_target_catalog_preserves_frozen_parameter_metadata(self):
        body = {**self.scene, "inputTypes": ["image"], "models": [
            self.member("helmet", target="mobile"), self.member("helmet", 1, target="pc")], "plans": []}
        self.assertEqual(201, self.create(body).status_code)
        approved = self.client.post(self.scenes + "/safety/approval", headers=self.owner,
            json={"approved": True, "expectedRevision": 1, "reason": "isolated metadata review"})
        self.assertEqual(200, approved.status_code, approved.text)
        first = self.client.get(self.scenes, headers=self.user).json()["scenes"][0]
        self.assertEqual([], first["plans"])
        self.assertTrue(first["available"])
        for member in first["models"]:
            self.assertTrue(member["executionReady"])
            snapshot = member["parameterSnapshot"]
            self.assertEqual((2, "inherited", 0, None), tuple(
                snapshot[key] for key in ("schemaVersion", "source", "inheritedRevision", "updatedAt")))
            self.assertNotIn("audit", snapshot)
            self.assertNotIn("updatedBy", snapshot)
            profile = self.client.get(member["parameterUrl"], headers=self.user)
            self.assertEqual(200, profile.status_code, profile.text)
            self.assertEqual(snapshot, {key: profile.json()[key] for key in snapshot})

            platform = "android" if member["target"] == "mobile" else "server"
            model = main.model_catalog.get(member["modelId"], member["version"])
            values = main.model_parameter_store.get(model, platform, self.project_id)
            values["detection"]["confidenceThreshold"] = .4
            main.model_parameter_store.save(model, platform, values, "owner", 0, self.project_id)
        second = self.client.get(self.scenes, headers=self.user).json()["scenes"][0]
        self.assertEqual(first, second)
        self.assertFalse(main.streams)

    def test_stale_revision_invalid_members_and_duplicate_creation_are_atomic(self):
        self.assertEqual(201, self.create().status_code)
        self.assertEqual(409, self.create().status_code)
        path = self.scenes + "/safety"
        self.assertEqual(409, self.client.patch(path, headers=self.owner, json={"expectedRevision": 9, "name": "bad"}).status_code)
        invalid = self.client.put(path + "/models", headers=self.owner, json={"expectedRevision": 1,
            "models": [{"projectModelId": "missing-project-model", "position": 0, "execution": "single"}]})
        self.assertEqual(404, invalid.status_code)
        row = self.client.get(path, headers=self.owner).json()
        self.assertEqual((1, "现场安全", "helmet"), (row["revision"], row["name"], row["models"][0]["modelId"]))
        audits = [a for a in memory_audits_for_tests()["project"] if a["action"].startswith("scene.")]
        self.assertEqual(1, len(audits))

    def test_validation_rejects_invalid_inputs_positions_duplicates_null_and_unknown_fields(self):
        cases = [{"inputTypes": []}, {"inputTypes": ["image", "image"]}, {"inputTypes": ["audio"]},
                 {"models": []}, {"models": [self.member("helmet", 2)]},
                 {"models": [self.member("helmet"), self.member("helmet", 1)]},
                 {"models": [{**self.member("helmet"), "target": "invalid"}]}, {"approved": True},
                 {"expectedRevision": True}, {"sceneId": "../escape"}]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(422, self.create({**self.scene, **changes}).status_code)
        self.assertEqual(201, self.create().status_code)
        for changes in ({"name": None}, {"enabled": None}, {}, {"inputTypes": ["image", "image"]}):
            self.assertEqual(422, self.client.patch(self.scenes + "/safety", headers=self.owner,
                json={"expectedRevision": 1, **changes}).status_code)

    def test_members_require_published_matching_ready_target_and_input(self):
        registry = main.model_catalog._load()
        row = registry["models"][0]
        for changes, expected in (({"supportedTargets": ["mobile"]}, "model_target_not_supported"),
                                  ({"status": "REVOKED"}, "model_not_published"),
                                  ({"publishedTargets": ["mobile"]}, "model_target_not_published"),
                                  ({"inputTypes": ["image"]}, "scene_input_not_supported")):
            original = dict(row)
            row.update(changes)
            main.model_catalog._save(registry)
            result = self.create()
            self.assertEqual(409, result.status_code, result.text)
            self.assertEqual(expected, result.json()["detail"]["code"])
            row.clear()
            row.update(original)
        row["supportedTargets"] = ["pc", "mobile"]
        main.model_catalog._save(registry)
        (Path(self.temp.name) / row["artifacts"][0]["path"]).unlink()
        self.assertEqual("model_target_not_ready", self.create().json()["detail"]["code"])
        self.assertEqual([], self.scene_store.list(self.project_id))

    def test_single_input_scenes_accept_matching_members_and_reject_wider_inputs_atomically(self):
        for target in ("pc", "mobile"):
            for kind in ("image", "video"):
                with self.subTest(target=target, input=kind):
                    scene_id = f"input-{target}-{kind}"
                    member = {**self.member("helmet", target=target), "inputTypes": ["image", "video"]}
                    body = {**self.scene, "sceneId": scene_id, "inputTypes": [kind], "models": [member]}
                    rejected = self.create(body)
                    self.assertEqual(409, rejected.status_code, rejected.text)
                    self.assertEqual("scene_input_not_supported", rejected.json()["detail"]["code"])
                    self.assertIsNone(self.scene_store.get(self.project_id, scene_id))
                    created = self.create({**body, "models": [{**member, "inputTypes": [kind]}]})
                    self.assertEqual(201, created.status_code, created.text)
                    self.assertEqual([kind], created.json()["inputTypes"])
                    self.assertEqual([kind], created.json()["models"][0]["inputTypes"])
                    self.assertEqual([kind], created.json()["plans"][0]["inputTypes"])
                    self.assertFalse(created.json()["approved"])
        self.assertFalse(main.streams)

    def test_model_purpose_cannot_bypass_published_scene_gate(self):
        registry = main.model_catalog._load()
        row = next(row for row in registry["models"] if row["modelId"] == "helmet" and row["version"] == "1.0.0")
        row.update(purpose="development", status="READY", releaseEligible=False, publishedTargets=[])
        main.model_catalog._save(registry)
        # Purpose is ignored: a ready but unpublished model cannot be assigned in any environment.
        denied = self.create()
        self.assertEqual(409, denied.status_code)
        self.assertEqual("model_not_published", denied.json()["detail"]["code"])

        created = self.create()
        self.assertEqual(409, created.status_code)
        self.assertEqual("model_not_published", created.json()["detail"]["code"])

    def test_disable_after_revocation_and_project_suspend_blocks_write(self):
        self.assertEqual(201, self.create().status_code)
        registry = main.model_catalog._load()
        registry["models"][0]["status"] = "REVOKED"
        main.model_catalog._save(registry)
        disabled = self.client.patch(self.scenes + "/safety", headers=self.owner, json={"expectedRevision": 1, "enabled": False})
        self.assertEqual(200, disabled.status_code, disabled.text)
        # Use the public project lifecycle endpoint, not a test-only state override.
        project = self.client.get(self.project_path, headers=self.headers).json()
        suspended = self.client.post(self.project_path + "/suspend", headers=self.headers,
            json={"expectedRevision": project["revision"], "reason": "test suspension"})
        self.assertEqual(200, suspended.status_code, suspended.text)
        self.assertEqual(403, self.create({**self.scene, "sceneId": "blocked"}).status_code)

    def test_inventory_authorization_rejects_disabled_cross_project_and_allows_reuse(self):
        cross_project = self.create({**self.scene, "models": [
            self.member("helmet", project_model_id=self.other_project_model_id)]})
        self.assertEqual(404, cross_project.status_code)
        self.assertEqual("project_model_not_found", cross_project.json()["detail"]["code"])

        project_model_id = self.project_models[("helmet", "1.0.0", "pc")]
        disabled = self._assign({**self.body, "enabled": False, "expectedRevision": 1})
        self.assertEqual(200, disabled.status_code, disabled.text)
        denied = self.create()
        self.assertEqual(409, denied.status_code)
        self.assertEqual("project_model_disabled", denied.json()["detail"]["code"])
        enabled = self._assign({**self.body, "enabled": True, "expectedRevision": 2})
        self.assertEqual(200, enabled.status_code, enabled.text)

        first = self.create()
        second = self.create({**self.scene, "sceneId": "entrance"})
        self.assertEqual([201, 201], [first.status_code, second.status_code])
        self.assertEqual(project_model_id, first.json()["models"][0]["projectModelId"])

    def test_inventory_parameter_refresh_requires_explicit_scene_member_confirmation(self):
        created = self.create()
        self.assertEqual(201, created.status_code, created.text)
        model = main.model_catalog.get("helmet", "1.0.0")
        profile = main.model_parameter_store.get(model, "server", self.project_id)
        profile["detection"]["confidenceThreshold"] = 0.21
        main.model_parameter_store.save(model, "server", profile, "test", 0, self.project_id)
        refreshed = self._assign({**self.body, "parameterRevision": 1, "expectedRevision": 1})
        self.assertEqual(200, refreshed.status_code, refreshed.text)
        denied = self.client.post(self.scenes + "/safety/approval", headers=self.owner,
            json={"approved": True, "expectedRevision": 1, "reason": "reviewed"})
        self.assertEqual(409, denied.status_code)
        self.assertEqual("project_model_revision_conflict", denied.json()["detail"]["code"])
        confirmed = self.client.put(self.scenes + "/safety/models", headers=self.owner,
            json={"expectedRevision": 1, "models": [self.member("helmet")]})
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        approved = self.client.post(self.scenes + "/safety/approval", headers=self.owner,
            json={"approved": True, "expectedRevision": 2, "reason": "reviewed"})
        self.assertEqual(200, approved.status_code, approved.text)
        self.assertEqual(1, approved.json()["models"][0]["parameterSnapshot"]["revision"])


class SceneSqliteTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(".tmp") / "m33-t39-tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        if getattr(self, "use_postgresql", False):
            from postgresql_support import isolated_postgresql_url
            self.postgres = isolated_postgresql_url("m36_scene")
            database_url = self.postgres.__enter__()
            self.addCleanup(lambda: self.postgres.__exit__(None, None, None))
        else:
            database_url = f"sqlite:///{(Path(self.temp.name) / 'scenes.db').as_posix()}"
        self.db = DatabaseManager(database_url)
        self.addCleanup(self.db.close)
        Base.metadata.create_all(self.db.engine)
        with self.db.session() as session:
            session.add(ProjectRecord(project_id="p1", project_code="p1", display_name="P1", lifecycle_state="ACTIVE"))
            session.add(ProjectRecord(project_id="p2", project_code="p2", display_name="P2", lifecycle_state="ACTIVE"))
        from unittest.mock import Mock
        self.catalog = Mock()
        self.catalog.get.side_effect = lambda model_id, version: {"modelId": model_id, "version": version,
            "labels": ["head"], "name": model_id, "status": "PUBLISHED", "releaseEligible": True,
            "supportedTargets": ["pc"], "serverReady": True, "inputTypes": ["video"],
            "targetReadiness": {"pc": {"ready": True}}, "targetReleaseEligible": {"pc": True}}
        from app.model_parameters import ModelParameterStore
        from app.project_model_assignments import ProjectModelAssignments
        parameters = ModelParameterStore(Path(self.temp.name) / "parameters.json", self.db)
        self.assignments = ProjectModelAssignments(self.db, self.catalog, parameters)
        with self.db.session() as session:
            for project_id in ("p1", "p2"):
                for position, model_id in enumerate(("helmet", "person")):
                    project_model_id = f"pm-{project_id}-{model_id}"
                    session.add(ProjectModelAssignmentRecord(
                        assignment_id=project_model_id, project_id=project_id, model_id=model_id,
                        model_version="1.0.0", parameter_platform="server", parameter_revision=0,
                        parameter_snapshot={"projectId": project_id, "modelId": model_id,
                            "modelVersion": "1.0.0", "platform": "server", "revision": 0,
                            "schemaVersion": 2, "source": "default", "updatedAt": None,
                            "detection": {}, "alertRules": []},
                        enabled=True, revision=1,
                    ))
        self.store = ProjectScenes(self.db, self.catalog, self.assignments)
        self.changes = {"name": "Safety", "inputTypes": ["video"], "enabled": True,
                        "models": [self.member("helmet"), self.member("person", 1)]}

    @staticmethod
    def member(model_id, position=0):
        return {"projectModelId": f"pm-p1-{model_id}", "position": position, "execution": "single"}

    def test_reopen_order_replace_isolation_and_revision(self):
        saved = self.store.save("p1", "safety", self.changes, 0, creating=True)
        self.db.close()
        reopened = ProjectScenes(self.db, self.catalog, self.assignments)
        self.assertEqual(saved, reopened.get("p1", "safety"))
        self.assertIsNone(reopened.get("p2", "safety"))
        with self.assertRaises(HTTPException):
            reopened.save("p1", "safety", {"name": "Stale"}, 0)
        changed = reopened.save("p1", "safety", {"models": [self.member("person")]}, 1)
        self.assertEqual((2, 1), (changed["revision"], len(changed["models"])))
        with self.db.session() as session:
            self.assertEqual(1, len(session.scalars(select(ProjectSceneMemberRecord)).all()))

    def test_audit_failure_rolls_back_scene_and_members_and_inactive_guard(self):
        self.store.save("p1", "safety", self.changes, 0, creating=True)
        with patch("app.project_scenes.audit_change", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.store.save("p1", "safety", {"models": [self.member("person")]}, 1)
        self.assertEqual(1, self.store.get("p1", "safety")["revision"])
        self.assertEqual(2, len(self.store.get("p1", "safety")["models"]))
        with self.db.session() as session:
            session.get(ProjectRecord, "p1").lifecycle_state = "ARCHIVED"
        with self.assertRaises(HTTPException) as error:
            self.store.save("p1", "safety", {"enabled": False}, 1)
        self.assertEqual(403, error.exception.status_code)

    def test_new_scene_audit_failure_leaves_no_partial_data(self):
        with patch("app.project_scenes.audit_change", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.store.save("p1", "safety", self.changes, 0, creating=True)
        self.assertIsNone(self.store.get("p1", "safety"))
        with self.db.session() as session:
            self.assertEqual([], session.scalars(select(ProjectSceneMemberRecord)).all())

    def test_approval_persists_audit_and_rechecks_membership_inside_transaction(self):
        from types import SimpleNamespace
        from app.auth import Principal
        from app.database import AccountRecord, ProjectMembershipRecord, ProjectAuditEventRecord
        with self.db.session() as session:
            session.add(AccountRecord(account_id="owner", username="scene-owner", password_hash="not-a-login",
                role="operator", platform_role="NORMAL_USER", enabled=True))
            session.flush()
            session.add(ProjectMembershipRecord(project_id="p1", account_id="owner",
                project_role="PROJECT_OWNER", enabled=True, revision=1))
        context = SimpleNamespace(project_id="p1", project_role="PROJECT_OWNER",
            principal=Principal("owner", "scene-owner", "operator", "NORMAL_USER"))
        self.store.save("p1", "safety", self.changes, 0, creating=True, context=context, request_id="create")
        approved = self.store.save("p1", "safety", {"approved": True}, 1, context=context,
            request_id="review", approval_reason="reviewed")
        self.assertTrue(approved["approved"])
        self.db.close()
        self.assertTrue(self.store.get("p1", "safety")["approved"])
        with self.db.session() as session:
            audit = session.scalar(select(ProjectAuditEventRecord).where(ProjectAuditEventRecord.action == "scene.approval"))
            self.assertEqual(("owner", "review", 1, 2),
                (audit.actor_account_id, audit.request_id, audit.previous_revision, audit.new_revision))
            self.assertEqual("reviewed", audit.change_summary["after"]["reason"])
            session.get(ProjectMembershipRecord, ("p1", "owner")).enabled = False
        with self.assertRaises(HTTPException) as error:
            self.store.save("p1", "safety", {"approved": False}, 2, context=context, approval_reason="revoked")
        self.assertEqual(403, error.exception.status_code)
        self.assertEqual(2, self.store.get("p1", "safety")["revision"])


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL schema")
class ScenePostgreSqlTests(SceneSqliteTests):
    use_postgresql = True

    def test_independent_stores_serialize_first_creation_and_updates(self):
        for revision in (0, 1):
            barrier = Barrier(2)
            stores = [ProjectScenes(self.db, self.catalog, self.assignments) for _ in range(2)]
            # Simulate separate worker processes; PostgreSQL project row is the lock.
            from threading import RLock
            for store in stores:
                store._lock = RLock()
            def worker(store):
                barrier.wait(timeout=10)
                try:
                    store.save("p1", "safety", self.changes, revision, creating=revision == 0)
                    return "saved"
                except HTTPException as exc:
                    self.assertEqual(409, exc.status_code)
                    return "conflict"
            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertCountEqual(["saved", "conflict"], list(executor.map(worker, stores)))


class SceneMigrationTests(unittest.TestCase):
    def test_additive_migration_and_nonempty_downgrade_guard(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import inspect, text
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite:///{(Path(directory) / 'migration.db').as_posix()}"
            db = DatabaseManager(url)
            try:
                # Existing pre-M36 schema; preserve old assignments unchanged.
                config = Config("alembic.ini")
                config.set_main_option("sqlalchemy.url", url)
                command.upgrade(config, "20261019_13")
                command.upgrade(config, "20261019_14")
                command.upgrade(config, "20261019_14")
                self.assertIn("project_scene_members", inspect(db.engine).get_table_names())
                with db.session() as session:
                    session.add(ProjectRecord(project_id="p1", project_code="p1", display_name="P1"))
                    session.flush()
                    session.execute(text("INSERT INTO project_scenes (project_id, scene_id, display_name, input_types, enabled, approved, revision) "
                        "VALUES ('p1', 'safety', 'Safety', '[\"video\"]', 1, 0, 1)"))
                with self.assertRaisesRegex(RuntimeError, "scene data exists"):
                    command.downgrade(config, "20261019_13")
                with db.session() as session:
                    self.assertEqual("20261019_14", session.scalar(text("SELECT version_num FROM alembic_version")))
                self.assertIn("project_scenes", inspect(db.engine).get_table_names())
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
