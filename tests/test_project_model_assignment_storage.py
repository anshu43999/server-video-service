import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import text

from app.database import Base, DEFAULT_PROJECT_ID, DatabaseManager, ProjectRecord
from app.model_catalog import ModelCatalog
from app.model_parameters import ModelParameterStore
from app.project_model_assignments import AssignmentConflict, ProjectModelAssignments
from app.stream_config import StreamConfigStore, StreamConfiguration
from postgresql_support import isolated_postgresql_url
from test_project_model_assignments import release


class AssignmentStorageChecks:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "models").mkdir()
        registry = root / "models" / "registry.json"
        registry.write_text(json.dumps({"models": [release(root / "models", "helmet", "1.0.0"),
                                                       release(root / "models", "helmet", "2.0.0")]}), encoding="utf-8")
        self.database = DatabaseManager(self.database_url if hasattr(self, "database_url") else f"sqlite:///{(root / 'test.db').as_posix()}")
        self.addCleanup(self.database.close)
        if not hasattr(self, "database_url"):
            Base.metadata.create_all(self.database.engine)
        self.project_id = "assignment-" + os.urandom(5).hex()
        now = datetime.now(timezone.utc)
        with self.database.session() as session:
            if session.get(ProjectRecord, DEFAULT_PROJECT_ID) is None:
                session.add(ProjectRecord(project_id=DEFAULT_PROJECT_ID, project_code="default", display_name="Default", created_at=now, updated_at=now))
            session.add(ProjectRecord(project_id=self.project_id, project_code=self.project_id, display_name="A", created_at=now, updated_at=now))
        self.catalog = ModelCatalog(registry)
        self.profiles = ModelParameterStore(root / "profiles.json", self.database)
        self.streams = StreamConfigStore(self.database)
        self.store = ProjectModelAssignments(self.database, self.catalog, self.profiles, self.streams)

    def save(self, store=None, version="1.0.0", parameter=0, expected=0, enabled=True):
        return (store or self.store).save(self.project_id, "helmet", version, "pc", parameter, enabled, expected)

    def test_persisted_snapshots_versions_cas_and_project_isolation(self):
        saved = self.save()
        snapshot = self.store.snapshot(self.project_id, "helmet", "1.0.0", "server")
        self.assertEqual(1, saved["revision"])
        self.assertIsNone(self.store.snapshot(self.project_id, "helmet", "1.0.0", "android"))
        self.assertEqual([], self.store.assigned(DEFAULT_PROJECT_ID, "helmet"))
        self.database.close()
        reopened = ProjectModelAssignments(self.database, self.catalog, self.profiles, self.streams)
        self.assertEqual(snapshot, reopened.snapshot(self.project_id, "helmet", "1.0.0", "server"))
        with self.assertRaises(AssignmentConflict):
            self.save(store=reopened)
        model = self.catalog.get("helmet", "1.0.0")
        values = self.profiles.default_profile(model, "server")
        values["detection"]["confidenceThreshold"] = .4
        self.profiles.save(model, "server", values, "owner", 0, self.project_id)
        self.assertEqual(snapshot, reopened.snapshot(self.project_id, "helmet", "1.0.0", "server"))
        with self.assertRaises(AssignmentConflict):
            self.save(expected=1)
        updated = self.save(parameter=1, expected=1)
        self.assertIsNotNone(updated["parameterProfileKey"])
        self.assertEqual(.4, self.store.snapshot(self.project_id, "helmet", "1.0.0", "server")["detection"]["confidenceThreshold"])

    def test_active_stream_and_inactive_project_guards(self):
        self.save()
        self.streams.create(StreamConfiguration("camera", "Camera", "websocket", None, "helmet", False, .4, 10, True,
            project_id=self.project_id, model_version="1.0.0"))
        second = self.save(version="2.0.0", expected=0)
        self.assertEqual(("2.0.0", 1), (second["modelVersion"], second["revision"]))
        with self.assertRaises(AssignmentConflict):
            self.save(enabled=False, expected=1)
        self.streams.update("camera", project_id=self.project_id, enabled=False)
        self.save(version="2.0.0", expected=1)
        self.assertEqual("1.0.0", self.streams.get("camera", self.project_id).model_version)
        with self.database.session() as session:
            session.get(ProjectRecord, self.project_id).lifecycle_state = "SUSPENDED"
        self.assertFalse(self.store.project_active(self.project_id))
        with self.assertRaises(HTTPException) as error:
            self.save(version="2.0.0", expected=2)
        self.assertEqual(403, error.exception.status_code)

    def test_zero_revision_parameter_update_between_read_and_save_is_rejected(self):
        original = self.profiles.get
        model = self.catalog.get("helmet", "1.0.0")
        def race(model, platform, project_id=None):
            profile = original(model, platform, project_id)
            if project_id == self.project_id:
                self.profiles.save(model, platform, profile, "racing-owner", 0, project_id)
            return profile
        with patch.object(self.profiles, "get", side_effect=race):
            with self.assertRaises(AssignmentConflict):
                self.save()
        self.assertEqual([], self.store.list(self.project_id))


class AssignmentSqliteTests(AssignmentStorageChecks, unittest.TestCase):
    pass


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL schema")
class AssignmentPostgreSqlTests(AssignmentStorageChecks, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.postgres = isolated_postgresql_url("m33_assignment")
        cls.database_url = cls.postgres.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.postgres.__exit__(None, None, None)

    def test_independent_assignment_stores_serialize_first_insert_and_update(self):
        for revision in (0, 1):
            barrier = Barrier(2)
            stores = [ProjectModelAssignments(self.database, self.catalog, self.profiles, self.streams) for _ in range(2)]
            def worker(store):
                barrier.wait(timeout=10)
                try:
                    self.save(store=store, expected=revision)
                    return "saved"
                except AssignmentConflict:
                    return "conflict"
            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertCountEqual(["saved", "conflict"], list(executor.map(worker, stores)))

    def test_migration_legacy_disabled_and_pinned_data_blocks_downgrade(self):
        with isolated_postgresql_url("m33_assignment_legacy", revision="20261010_08") as url:
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
            command.downgrade(config, "20261010_08")
            db = DatabaseManager(url)
            try:
                with db.session() as session:
                    session.execute(text("INSERT INTO project_model_assignments (assignment_id, project_id, scenario, model_id, model_version, enabled, revision, created_at, updated_at) VALUES ('legacy', :pid, 'ppe', 'helmet', '1.0.0', true, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"pid": DEFAULT_PROJECT_ID})
                command.upgrade(config, "20261012_11")
                command.upgrade(config, "20261012_11")
                with db.session() as session:
                    row = session.execute(text("SELECT enabled, parameter_revision, parameter_snapshot FROM project_model_assignments WHERE assignment_id='legacy'")).one()
                    self.assertEqual((False, 0, {}), tuple(row))
                    session.execute(text("UPDATE project_model_assignments SET parameter_snapshot = CAST(:snapshot AS jsonb) WHERE assignment_id='legacy'"),
                                    {"snapshot": json.dumps({"revision": 0})})
                with self.assertRaisesRegex(RuntimeError, "pinned parameters exist"):
                    command.downgrade(config, "20261010_08")
                with db.session() as session:
                    self.assertEqual("20261012_11", session.scalar(text("SELECT version_num FROM alembic_version")))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
