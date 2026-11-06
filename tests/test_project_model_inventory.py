import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

from app.database import ProjectRecord
from app.project_model_assignments import AssignmentConflict, ProjectModelAssignments
from app.stream_config import StreamConfiguration
from postgresql_support import isolated_postgresql_url
from test_project_model_assignments import ModelApiFixture
from test_project_model_assignment_storage import AssignmentStorageChecks
import app.main as main


class ProjectModelInventoryApiTests(ModelApiFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.assignments = self.project_path + "/model-assignments"
        self.body = {
            "modelId": "helmet", "modelVersion": "1.0.0",
            "target": "pc", "parameterRevision": 0,
            "enabled": True, "expectedRevision": 0,
        }

    def test_each_target_accepts_multiple_exact_model_releases(self):
        first = self._assign()
        second = self._assign({**self.body, "modelVersion": "2.0.0"})
        third = self._assign({**self.body, "modelId": "secret"})
        self.assertEqual([200, 200, 200], [first.status_code, second.status_code, third.status_code])

        rows = self.client.get(self.assignments, headers=self.owner, params={"target": "pc"}).json()["assignments"]
        self.assertEqual(3, len(rows))
        self.assertEqual({("helmet", "1.0.0"), ("helmet", "2.0.0"), ("secret", "1.0.0")},
                         {(row["modelId"], row["modelVersion"]) for row in rows})
        self.assertTrue(all(row["target"] == "pc" for row in rows))
        self.assertTrue(all("scenario" not in row for row in rows))

    def test_pc_and_mobile_are_independent_inventory_items(self):
        pc = self._assign()
        mobile = self._assign({**self.body, "target": "mobile"})
        self.assertEqual([200, 200], [pc.status_code, mobile.status_code])
        self.assertNotEqual(pc.json()["projectModelId"], mobile.json()["projectModelId"])
        self.assertEqual(1, len(self.client.get(self.assignments, headers=self.owner, params={"target": "pc"}).json()["assignments"]))
        self.assertEqual(1, len(self.client.get(self.assignments, headers=self.owner, params={"target": "mobile"}).json()["assignments"]))

    def test_cas_permissions_and_explicit_remove(self):
        self.assertEqual(403, self._assign(headers=self.user).status_code)
        saved = self._assign()
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(409, self._assign().status_code)
        project_model_id = saved.json()["projectModelId"]
        self.assertEqual(403, self.client.delete(
            f"{self.assignments}/{project_model_id}", headers=self.user, params={"expectedRevision": 1}).status_code)
        removed = self.client.delete(
            f"{self.assignments}/{project_model_id}", headers=self.owner, params={"expectedRevision": 1})
        self.assertEqual(200, removed.status_code, removed.text)
        self.assertEqual([], self.client.get(self.assignments, headers=self.owner).json()["assignments"])

    def test_old_scenario_write_route_is_not_supported(self):
        response = self.client.put(self.assignments + "/ppe", headers=self.owner, json=self.body)
        self.assertEqual(405, response.status_code)


class ProjectModelInventoryMigrationTests(unittest.TestCase):
    def test_scenario_assignments_are_not_migrated_into_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite:///" + (Path(directory) / "migration.db").as_posix()
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
            command.upgrade(config, "20261029_29")
            engine = create_engine(url)
            try:
                with engine.begin() as connection:
                    connection.execute(text(
                        "INSERT INTO project_model_assignments "
                        "(assignment_id, project_id, scenario, model_id, model_version, enabled, revision, created_at, updated_at) "
                        "VALUES ('old-assignment', :project_id, 'ppe', 'helmet', '1.0.0', true, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ), {"project_id": main.DEFAULT_PROJECT_ID})
                command.upgrade(config, "20261102_30")
                with engine.connect() as connection:
                    self.assertEqual(0, connection.scalar(text("SELECT COUNT(*) FROM project_model_assignments")))
                columns = {column["name"] for column in inspect(engine).get_columns("project_model_assignments")}
                self.assertNotIn("scenario", columns)
                self.assertIn("model_version", columns)
            finally:
                engine.dispose()

    def test_inventory_downgrade_does_not_restore_scenario_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite:///" + (Path(directory) / "migration.db").as_posix()
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
            command.upgrade(config, "20261102_30")
            with self.assertRaisesRegex(RuntimeError, "downgrade is unsupported"):
                command.downgrade(config, "20261029_29")
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    self.assertEqual(
                        "20261102_30",
                        connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
                    )
                columns = {column["name"] for column in inspect(engine).get_columns("project_model_assignments")}
                self.assertNotIn("scenario", columns)
            finally:
                engine.dispose()


class ProjectModelInventorySqliteTests(AssignmentStorageChecks, unittest.TestCase):
    def save(self, store=None, version="1.0.0", parameter=0, expected=0, enabled=True):
        return (store or self.store).save(
            self.project_id, "helmet", version, "pc", parameter, enabled, expected
        )

    def save_inventory(self, model_id="helmet", version="1.0.0", target="pc", parameter=0, expected=0, enabled=True):
        return self.store.save(self.project_id, model_id, version, target, parameter, enabled, expected)

    def test_active_stream_and_inactive_project_guards(self):
        first = self.save()
        self.streams.create(StreamConfiguration(
            "camera", "Camera", "websocket", None, "helmet", False, .4, 10, True,
            project_id=self.project_id, model_version="1.0.0"
        ))

        second = self.save(version="2.0.0")
        self.assertNotEqual(first["projectModelId"], second["projectModelId"])
        with self.assertRaises(AssignmentConflict):
            self.save(enabled=False, expected=1)
        with self.assertRaises(AssignmentConflict):
            self.store.remove(self.project_id, first["projectModelId"], 1)

        self.streams.update("camera", project_id=self.project_id, enabled=False)
        disabled = self.save(enabled=False, expected=1)
        self.assertFalse(disabled["enabled"])

        with self.database.session() as session:
            session.get(ProjectRecord, self.project_id).lifecycle_state = "SUSPENDED"
        self.assertFalse(self.store.project_active(self.project_id))
        with self.assertRaises(HTTPException) as error:
            self.save(version="2.0.0", expected=1)
        self.assertEqual(403, error.exception.status_code)

    def test_multiple_pc_rows_survive_reopen_and_filter(self):
        first = self.save_inventory()
        second = self.save_inventory(version="2.0.0")
        self.assertNotEqual(first["projectModelId"], second["projectModelId"])
        self.database.close()
        reopened = ProjectModelAssignments(self.database, self.catalog, self.profiles, self.streams)
        self.assertEqual(2, len(reopened.list(self.project_id, "pc")))
        self.assertEqual([], reopened.list(self.project_id, "mobile"))

    def test_stale_revision_and_remove_are_fail_closed(self):
        saved = self.save_inventory()
        with self.assertRaises(AssignmentConflict):
            self.save_inventory()
        with self.assertRaises(AssignmentConflict):
            self.store.remove(self.project_id, saved["projectModelId"], 0)
        self.assertTrue(self.store.remove(self.project_id, saved["projectModelId"], 1)["removed"])
        self.assertEqual([], self.store.list(self.project_id))

    def test_frozen_profile_metadata_survives_assignment_and_scene_restart(self):
        from app.project_scenes import ProjectScenes

        saved = self.save_inventory()
        inherited = self.store.resolve(self.project_id, saved["projectModelId"])["parameterSnapshot"]
        self.assertEqual((2, "inherited", 0, None), tuple(
            inherited[key] for key in ("schemaVersion", "source", "inheritedRevision", "updatedAt")))
        self.assertNotIn("audit", inherited)
        self.assertNotIn("updatedBy", inherited)

        scenes = ProjectScenes(self.database, self.catalog, self.store)
        scenes.save(self.project_id, "metadata", {
            "name": "Metadata", "inputTypes": ["image"], "enabled": True,
            "models": [{"projectModelId": saved["projectModelId"], "position": 0, "execution": "single"}],
        }, 0, creating=True)
        scenes.save(self.project_id, "metadata", {"approved": True}, 1, approval_reason="isolated test")

        model = self.catalog.get("helmet", "1.0.0")
        values = self.profiles.get(model, "server", self.project_id)
        values["detection"]["confidenceThreshold"] = .4
        custom = self.profiles.save(model, "server", values, "owner", 0, self.project_id)
        self.save_inventory(parameter=1, expected=1)
        current = self.store.resolve(self.project_id, saved["projectModelId"])["parameterSnapshot"]
        self.assertEqual((2, "custom", None, custom["updatedAt"]), tuple(
            current[key] for key in ("schemaVersion", "source", "inheritedRevision", "updatedAt")))
        self.assertNotIn("updatedBy", current)
        self.database.close()
        reopened = ProjectScenes(self.database, self.catalog, self.store)
        self.assertEqual(inherited, reopened.get(self.project_id, "metadata")["models"][0]["parameterSnapshot"])
        self.assertEqual(current, self.store.resolve(self.project_id, saved["projectModelId"])["parameterSnapshot"])


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL schema")
class ProjectModelInventoryPostgreSqlTests(ProjectModelInventorySqliteTests):
    @classmethod
    def setUpClass(cls):
        cls.postgres = isolated_postgresql_url("m33_project_model_inventory")
        cls.database_url = cls.postgres.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.postgres.__exit__(None, None, None)

    def test_parallel_first_assignment_serializes_by_project(self):
        barrier = Barrier(2)
        stores = [ProjectModelAssignments(self.database, self.catalog, self.profiles, self.streams) for _ in range(2)]

        def assign(store):
            barrier.wait(timeout=10)
            try:
                self.save(store=store)
                return "saved"
            except AssignmentConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(["saved", "conflict"], list(executor.map(assign, stores)))

    def test_migration_discards_legacy_scenario_rows(self):
        with isolated_postgresql_url("m33_project_model_legacy", revision="20261029_29") as url:
            engine = create_engine(url)
            try:
                with engine.begin() as connection:
                    connection.execute(text(
                        "INSERT INTO project_model_assignments "
                        "(assignment_id, project_id, scenario, model_id, model_version, parameter_platform, "
                        "parameter_revision, parameter_snapshot, enabled, revision, created_at, updated_at) "
                        "VALUES ('legacy-inventory-row', :project_id, 'ppe', 'helmet', '1.0.0', 'server', "
                        "0, CAST('{}' AS jsonb), true, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ), {"project_id": main.DEFAULT_PROJECT_ID})
                config = Config("alembic.ini")
                config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
                command.upgrade(config, "head")
                with engine.connect() as connection:
                    self.assertEqual(0, connection.scalar(text("SELECT COUNT(*) FROM project_model_assignments")))
                columns = {column["name"] for column in inspect(engine).get_columns("project_model_assignments")}
                self.assertNotIn("scenario", columns)
                self.assertIn("model_version", columns)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
