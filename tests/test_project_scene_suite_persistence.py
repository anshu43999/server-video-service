import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.database import Base, DatabaseManager, ProjectRecord, ProjectModelAssignmentRecord
from app.model_parameters import ModelParameterStore
from app.project_model_assignments import ProjectModelAssignments
from app.project_scenes import ProjectScenes


class SceneSuitePersistenceTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(".tmp") / "m33-t39-suite"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.db = DatabaseManager(f"sqlite:///{(Path(self.temp.name) / 'suite.db').as_posix()}")
        self.addCleanup(self.db.close)
        Base.metadata.create_all(self.db.engine)
        with self.db.session() as session:
            session.add_all([
                ProjectRecord(project_id="p1", project_code="p1", display_name="P1", lifecycle_state="ACTIVE"),
                ProjectRecord(project_id="p2", project_code="p2", display_name="P2", lifecycle_state="ACTIVE"),
            ])
        self.catalog = Mock()
        self.catalog.get.side_effect = lambda model_id, version: {
            "modelId": model_id, "version": version, "status": "PUBLISHED", "releaseEligible": True,
            "supportedTargets": ["mobile"], "targetReadiness": {"mobile": {"ready": True}},
            "inputTypes": ["image", "video"], "publishedTargets": ["mobile"],
            "targetReleaseEligible": {"mobile": True},
        }
        parameters = ModelParameterStore(Path(self.temp.name) / "parameters.json", self.db)
        self.assignments = ProjectModelAssignments(self.db, self.catalog, parameters)
        with self.db.session() as session:
            for project_id in ("p1", "p2"):
                for key, model_id, version in (("helmet", "helmet", "1.0.0"),
                                               ("ppe-video", "ppe", "2.0.0"),
                                               ("person-image", "person", "1.0.0")):
                    session.add(ProjectModelAssignmentRecord(
                        assignment_id=f"pm-{project_id}-{key}", project_id=project_id, model_id=model_id,
                        model_version=version, parameter_platform="android", parameter_revision=0,
                        parameter_snapshot={"projectId": project_id, "modelId": model_id,
                            "modelVersion": version, "platform": "android", "revision": 0,
                            "detection": {}, "alertRules": []}, enabled=True, revision=1,
                    ))
        self.store = ProjectScenes(self.db, self.catalog, self.assignments)

    @staticmethod
    def changes():
        return {
            "name": "现场安全",
            "inputTypes": ["image", "video"],
            "enabled": True,
            "models": [
                {"memberId": "helmet-image", "projectModelId": "pm-p1-helmet",
                 "position": 0, "inputTypes": ["image"], "execution": "single"},
                {"memberId": "ppe-video", "projectModelId": "pm-p1-ppe-video",
                 "position": 1, "inputTypes": ["video"], "execution": "single"},
                {"memberId": "ppe-image", "projectModelId": "pm-p1-person-image",
                 "position": 2, "inputTypes": ["image"], "execution": "single"},
            ],
            "plans": [
                {"planId": "image", "name": "静态识别", "inputTypes": ["image"],
                 "memberIds": ["helmet-image"], "execution": "single", "enabled": True},
                {"planId": "video", "name": "视频流识别", "inputTypes": ["video"],
                 "memberIds": ["ppe-video"], "execution": "single", "enabled": True},
                {"planId": "combined", "name": "联合识别", "inputTypes": ["image"],
                 "memberIds": ["helmet-image", "ppe-image"], "execution": "sync", "enabled": True},
            ],
        }

    def test_mixed_members_and_plans_survive_restart_and_are_project_isolated(self):
        saved = self.store.save("p1", "safety", self.changes(), 0, creating=True)
        self.assertEqual({"helmet-image", "ppe-video", "ppe-image"}, {row["memberId"] for row in saved["models"]})
        self.assertEqual({"image", "video", "combined"}, {row["planId"] for row in saved["plans"]})
        self.assertIsNone(self.store.get("p2", "safety"))
        reopened = ProjectScenes(self.db, self.catalog, self.assignments)
        loaded = reopened.get("p1", "safety")
        self.assertEqual(saved, loaded)
        self.assertEqual(["helmet-image"], next(plan for plan in loaded["plans"] if plan["planId"] == "image")["memberIds"])
        with self.assertRaises(HTTPException) as error:
            reopened.save("p1", "safety", {"name": "stale"}, 0)
        self.assertEqual("revision_conflict", error.exception.detail["code"])

    def test_plan_cannot_reference_missing_member_or_incompatible_input(self):
        changes = self.changes()
        changes["plans"][0]["memberIds"] = ["missing"]
        with self.assertRaises(HTTPException) as error:
            self.store.save("p1", "safety", changes, 0, creating=True)
        self.assertEqual("invalid_scene_suite", error.exception.detail["code"])
        changes = self.changes()
        changes["plans"][0]["inputTypes"] = ["video"]
        with self.assertRaises(HTTPException) as error:
            self.store.save("p1", "safety", changes, 0, creating=True)
        self.assertEqual("scene_input_not_supported", error.exception.detail["code"])

    def test_migration_is_additive_and_idempotent(self):
        self.db.close()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", f"sqlite:///{(Path(self.temp.name) / 'migration.db').as_posix()}")
        command.upgrade(config, "20261020_17")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        db = DatabaseManager(config.get_main_option("sqlalchemy.url"))
        self.addCleanup(db.close)
        tables = set(inspect(db.engine).get_table_names())
        self.assertIn("project_scene_plans", tables)
        self.assertIn("project_scene_plan_members", tables)
        self.assertIn("project_scene_installations", tables)
        self.assertIn("camera_policy", {column["name"] for column in inspect(db.engine).get_columns("project_scene_plans")})
        columns = {column["name"] for column in inspect(db.engine).get_columns("project_scene_members")}
        self.assertTrue({"member_id", "input_types", "project_model_id"}.issubset(columns))

    def test_migration_discards_legacy_scene_members_without_inventory_identity(self):
        self.db.close()
        url = f"sqlite:///{(Path(self.temp.name) / 'legacy.db').as_posix()}"
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "20261020_17")
        db = DatabaseManager(url)
        with db.session() as session:
            session.execute(text("INSERT INTO projects (project_id, project_code, display_name, lifecycle_state, revision) VALUES ('p1', 'legacy-p1', 'P1', 'ACTIVE', 1)"))
            session.execute(text("INSERT INTO project_scenes (project_id, scene_id, display_name, input_types, enabled, approved, revision) VALUES ('p1', 'legacy', 'Legacy', :types, 1, 0, 1)"), {"types": '["image", "video"]'})
            session.execute(text("INSERT INTO project_scene_members (project_id, scene_id, position, model_id, model_version, target, execution, parameter_snapshot) VALUES ('p1', 'legacy', 0, 'helmet', '1.0.0', 'mobile', 'single', NULL)"))
        db.close()
        command.upgrade(config, "head")
        db = DatabaseManager(url)
        self.addCleanup(db.close)
        with db.session() as session:
            self.assertEqual(0, session.execute(text("SELECT COUNT(*) FROM project_scenes")).scalar_one())
            self.assertEqual(0, session.execute(text("SELECT COUNT(*) FROM project_scene_members")).scalar_one())


if __name__ == "__main__":
    unittest.main()
