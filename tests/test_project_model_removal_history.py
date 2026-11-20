"""Project inventory removal releases only deleted scene references."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

import app.main as main
from app.auth import Principal
from app.database import (AccountRecord, DatabaseManager, DEFAULT_PROJECT_ID, ProjectModelAssignmentRecord,
                          ProjectSceneMemberRecord)
from app.project_model_assignments import AssignmentConflict
from app.project_scenes import ProjectScenes
from app.stream_config import StreamConfiguration
from postgresql_support import isolated_postgresql_url
from test_project_model_assignments import ModelApiFixture
from test_project_model_assignment_storage import AssignmentStorageChecks


class HistoryRemovalApiTests(ModelApiFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.scenes = ProjectScenes(None, main.model_catalog, main.project_model_assignments)
        self.patches.enter_context(patch.object(main, "project_scenes", self.scenes))

    def test_deleted_scene_no_longer_blocks_inventory_but_live_disabled_scene_does(self):
        assigned = self._assign().json()
        inventory_id = assigned["projectModelId"]
        path = f"{self.project_path}/model-assignments/{inventory_id}"
        scene_path = self.project_path + "/scenes"
        for scene_id in ("old", "remaining"):
            created = self.client.post(scene_path, headers=self.owner, json={
                "sceneId": scene_id, "name": scene_id, "inputTypes": ["image"],
                "enabled": False, "expectedRevision": 0,
                "models": [{"projectModelId": inventory_id, "memberId": "helmet", "position": 0, "execution": "single"}],
            })
            self.assertEqual(201, created.status_code, created.text)
        before_catalog = main.model_catalog._load()
        for scene_id in ("old", "remaining"):
            blocked = self.client.delete(path, headers=self.owner, params={"expectedRevision": 1})
            self.assertEqual(409, blocked.status_code, blocked.text)
            self.assertIn(scene_id, blocked.json()["detail"]["message"])
            deleted = self.client.delete(scene_path + "/" + scene_id, headers={
                **self.owner, "If-Match": '"1"', "Idempotency-Key": "delete-" + scene_id})
            self.assertEqual(200, deleted.status_code, deleted.text)
        history = deepcopy(self.scenes.get(self.project_id, "old"))
        self.assertEqual(403, self.client.delete(path, headers=self.user, params={"expectedRevision": 1}).status_code)
        self.assertEqual(409, self.client.delete(path, headers=self.owner, params={"expectedRevision": 0}).status_code)
        with patch("app.project_model_assignments.audit_change", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.client.delete(path, headers=self.owner, params={"expectedRevision": 1})
        self.assertIsNotNone(main.project_model_assignments.get(self.project_id, inventory_id))
        removed = self.client.delete(path, headers=self.owner, params={"expectedRevision": 1})
        self.assertEqual(200, removed.status_code, removed.text)
        self.assertTrue(removed.json()["removed"])
        self.assertEqual(history, self.scenes.get(self.project_id, "old"))
        self.assertEqual(before_catalog, main.model_catalog._load())
        self.assertEqual(404, self.client.get(path, headers=self.owner).status_code)
        reassigned = self._assign()
        self.assertEqual(200, reassigned.status_code, reassigned.text)
        self.assertNotEqual(inventory_id, reassigned.json()["projectModelId"])
        self.assertEqual(inventory_id, self.scenes.get(self.project_id, "old")["models"][0]["projectModelId"])


class HistoryRemovalSqliteTests(unittest.TestCase):
    def setUp(self):
        AssignmentStorageChecks.setUp(self)
        with self.database.session() as session:
            session.add(AccountRecord(account_id="history-admin", username="history-admin", password_hash="not-login",
                                      role="admin", platform_role="PLATFORM_ADMIN", enabled=True))
        self.context = SimpleNamespace(project_id=self.project_id, project_role="PROJECT_OWNER",
                                       principal=Principal("history-admin", "history-admin", "admin", "PLATFORM_ADMIN"))
        if self.database.backend == "sqlite":
            with self.database.engine.connect() as connection:
                connection.execute(text("PRAGMA foreign_keys=ON"))
        self.scenes = ProjectScenes(self.database, self.catalog, self.store)
        self.saved = self.store.save(self.project_id, "helmet", "1.0.0", "pc", 0, True, 0, context=self.context)
        self.inventory_id = self.saved["projectModelId"]

    def make_scene(self, scene_id, *, enabled=False):
        return self.scenes.save(self.project_id, scene_id, {
            "name": scene_id, "inputTypes": ["image"], "enabled": enabled,
            "models": [{"projectModelId": self.inventory_id, "memberId": "helmet", "position": 0, "execution": "single"}],
            "plans": [{"planId": "photo", "name": "Photo", "inputTypes": ["image"],
                       "memberIds": ["helmet"], "execution": "single", "enabled": True}],
        }, 0, creating=True, context=self.context)

    def delete_scene(self, scene_id):
        return self.scenes.soft_delete(self.project_id, scene_id, 1, "delete-" + scene_id, context=self.context)

    def remove_inventory(self, revision=1):
        return self.store.remove(self.project_id, self.inventory_id, revision, context=self.context)

    def test_all_deleted_scenes_detach_without_losing_history_or_rebinding_on_readd(self):
        for scene_id in ("first", "second"):
            self.make_scene(scene_id)
            self.delete_scene(scene_id)
        history = deepcopy(self.scenes.list(self.project_id))
        catalog_before = self.catalog._load()
        self.assertTrue(self.remove_inventory()["removed"])
        self.assertIsNone(self.store.get(self.project_id, self.inventory_id))
        self.assertIsNone(self.store.resolve(self.project_id, self.inventory_id, enabled_only=False))
        self.assertEqual([], self.store.list(self.project_id))
        self.database.close()
        self.assertEqual(history, self.scenes.list(self.project_id))
        self.assertEqual([], self.scenes.list_catalog(self.project_id, manage=True))
        with self.database.session() as session:
            members = session.scalars(select(ProjectSceneMemberRecord).where(
                ProjectSceneMemberRecord.project_id == self.project_id)).all()
            self.assertEqual(2, len(members))
            self.assertTrue(all(m.project_model_id is None and m.archived_project_model_id == self.inventory_id for m in members))
        replacement = self.store.save(self.project_id, "helmet", "1.0.0", "pc", 0, True, 0, context=self.context)
        self.assertNotEqual(self.inventory_id, replacement["projectModelId"])
        self.assertEqual(history, self.scenes.list(self.project_id))
        self.assertEqual(catalog_before, self.catalog._load())
        with self.assertRaises(HTTPException) as error:
            self.scenes.save(self.project_id, "first", {"enabled": True}, 2, context=self.context)
        self.assertEqual("scene_removed", error.exception.detail["code"])

    def test_disabled_or_unapproved_live_scene_blocks_without_partial_detach(self):
        self.make_scene("deleted"); self.delete_scene("deleted")
        self.make_scene("still-live")
        with self.assertRaisesRegex(AssignmentConflict, "still-live"):
            self.remove_inventory()
        with self.database.session() as session:
            members = session.scalars(select(ProjectSceneMemberRecord).where(
                ProjectSceneMemberRecord.project_id == self.project_id)).all()
            self.assertTrue(all(m.project_model_id == self.inventory_id and m.archived_project_model_id is None for m in members))
        self.delete_scene("still-live")
        self.assertTrue(self.remove_inventory()["removed"])

    def test_active_stream_stale_revision_and_cross_project_checks_remain(self):
        self.make_scene("deleted"); self.delete_scene("deleted")
        self.streams.create(StreamConfiguration("camera", "Camera", "websocket", None, "helmet", False, .4, 10, True,
                                               project_id=self.project_id, model_version="1.0.0"))
        with self.assertRaisesRegex(AssignmentConflict, "active stream"):
            self.remove_inventory()
        self.streams.update("camera", project_id=self.project_id, enabled=False)
        with self.assertRaises(AssignmentConflict):
            self.remove_inventory(0)
        with self.assertRaises(HTTPException) as error:
            self.store.remove(DEFAULT_PROJECT_ID, self.inventory_id, 1)
        self.assertEqual(404, error.exception.status_code)
        self.assertTrue(self.remove_inventory()["removed"])

    def test_failed_audit_rolls_back_detach_and_delete(self):
        self.make_scene("deleted"); self.delete_scene("deleted")
        with patch("app.project_model_assignments.audit_change", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.remove_inventory()
        with self.database.session() as session:
            self.assertIsNotNone(session.get(ProjectModelAssignmentRecord, self.inventory_id))
            member = session.scalar(select(ProjectSceneMemberRecord).where(ProjectSceneMemberRecord.project_id == self.project_id))
            self.assertEqual(self.inventory_id, member.project_model_id)
            self.assertIsNone(member.archived_project_model_id)
        self.assertTrue(self.remove_inventory()["removed"])

    def test_android_removal_does_not_remove_pc_assignment_or_restore_old_scene(self):
        pc_id = self.inventory_id
        registry = self.catalog._load()
        for entry in registry["models"]:
            if entry["modelId"] == "helmet" and entry["version"] == "1.0.0":
                entry.update(androidReady=True, androidConverted=True, signatureStatus="signed")
        self.catalog._save(registry)
        self.profiles.publish(self.catalog.get("helmet", "1.0.0"), "android", "history-admin", 0, None)
        android = self.store.save(self.project_id, "helmet", "1.0.0", "mobile", 0, True, 0, context=self.context)
        self.inventory_id = android["projectModelId"]
        self.make_scene("android-deleted"); self.delete_scene("android-deleted")
        self.assertTrue(self.remove_inventory()["removed"])
        self.assertEqual([pc_id], [row["projectModelId"] for row in self.store.list(self.project_id)])
        history = self.scenes.get(self.project_id, "android-deleted")
        self.assertEqual(self.inventory_id, history["models"][0]["projectModelId"])
        self.assertEqual("mobile", history["models"][0]["target"])

    def test_foreign_key_and_history_identity_constraint_remain_enforced(self):
        self.make_scene("still-live")
        with self.assertRaises(IntegrityError):
            with self.database.session() as session:
                session.delete(session.get(ProjectModelAssignmentRecord, self.inventory_id))
                session.flush()
        with self.assertRaises(IntegrityError):
            with self.database.session() as session:
                member = session.scalar(select(ProjectSceneMemberRecord).where(ProjectSceneMemberRecord.project_id == self.project_id))
                member.project_model_id = None
                session.flush()


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL schema")
class HistoryRemovalPostgreSqlTests(HistoryRemovalSqliteTests):
    def setUp(self):
        scope = isolated_postgresql_url("history_removal")
        self.database_url = scope.__enter__()
        self.addCleanup(lambda: scope.__exit__(None, None, None))
        super().setUp()


class HistoryMigrationTests(unittest.TestCase):
    def check_upgrade(self, url):
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(config, "20261105_34")
        engine = create_engine(url)
        try:
            with engine.begin() as c:
                c.execute(text("INSERT INTO project_model_assignments (assignment_id,project_id,model_id,model_version,parameter_platform) VALUES ('history-model',:pid,'helmet','2','android')"), {"pid": DEFAULT_PROJECT_ID})
                c.execute(text("INSERT INTO project_scenes (project_id,scene_id,display_name,input_types,enabled,approved,revision,deleted_at) VALUES (:pid,'deleted','Deleted','[\"image\"]',false,false,2,CURRENT_TIMESTAMP),(:pid,'live','Live','[\"image\"]',false,false,1,NULL)"), {"pid": DEFAULT_PROJECT_ID})
                for scene_id in ("deleted", "live"):
                    c.execute(text("INSERT INTO project_scene_members (project_id,scene_id,position,member_id,model_id,model_version,target,execution,input_types,project_model_id,parameter_revision,parameter_snapshot) VALUES (:pid,:sid,0,'helmet','helmet','2','mobile','single','[\"image\"]','history-model',3,'{\"revision\": 3}')"), {"pid": DEFAULT_PROJECT_ID, "sid": scene_id})
                    c.execute(text("INSERT INTO project_scene_plans (project_id,scene_id,plan_id,display_name,input_types,execution,enabled) VALUES (:pid,:sid,'photo','Photo','[\"image\"]','single',true)"), {"pid": DEFAULT_PROJECT_ID, "sid": scene_id})
                    c.execute(text("INSERT INTO project_scene_plan_members (project_id,scene_id,plan_id,member_id,position) VALUES (:pid,:sid,'photo','helmet',0)"), {"pid": DEFAULT_PROJECT_ID, "sid": scene_id})
            with engine.connect() as c:
                before = [tuple(r) for r in c.execute(text("SELECT scene_id,project_model_id,parameter_snapshot FROM project_scene_members ORDER BY scene_id"))]
            database = DatabaseManager(url)
            try:
                with self.assertRaisesRegex(RuntimeError, "scene history reference schema"):
                    database.verify_schema()
            finally:
                database.close()
            command.upgrade(config, "head")
            database = DatabaseManager(url)
            try:
                self.assertEqual("ready", database.verify_schema()["schema"])
            finally:
                database.close()
            with engine.connect() as c:
                self.assertEqual(before, [tuple(r) for r in c.execute(text("SELECT scene_id,project_model_id,parameter_snapshot FROM project_scene_members ORDER BY scene_id"))])
                self.assertEqual(2, c.scalar(text("SELECT COUNT(*) FROM project_scene_plan_members")))
                self.assertEqual(0, c.scalar(text("SELECT COUNT(*) FROM project_scene_members WHERE archived_project_model_id IS NOT NULL")))
                self.assertEqual(1, c.scalar(text("SELECT COUNT(*) FROM project_model_assignments")))
            columns = {item["name"]: item for item in inspect(engine).get_columns("project_scene_members")}
            self.assertTrue(columns["project_model_id"]["nullable"])
            self.assertIn("archived_project_model_id", columns)
            self.assertTrue(any(fk["referred_table"] == "project_model_assignments" and fk["options"].get("ondelete") == "RESTRICT" for fk in inspect(engine).get_foreign_keys("project_scene_members")))
            with self.assertRaisesRegex(RuntimeError, "downgrade is unsupported"):
                command.downgrade(config, "20261105_34")
            with engine.connect() as c:
                self.assertEqual("20261117_35", c.scalar(text("SELECT version_num FROM alembic_version")))
        finally:
            engine.dispose()

    def test_sqlite_upgrade_preserves_existing_live_and_deleted_scenes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.check_upgrade("sqlite:///" + (Path(directory) / "migration.db").as_posix())

    @unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL schema")
    def test_postgresql_upgrade_preserves_existing_live_and_deleted_scenes(self):
        with isolated_postgresql_url("history_upgrade", revision="20261105_34") as url:
            self.check_upgrade(url)
