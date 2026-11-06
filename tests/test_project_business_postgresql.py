import copy
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from app.database import DatabaseManager, DEFAULT_PROJECT_ID, ModelParameterProfileRecord, ProjectRecord, AlertEventRecord
from app.alerts.rules import RuleRegistry, RuleConflict
from app.alerts.verification import AlertVerificationStore, VerificationConfigConflict
from app.alerts.verification_provider import VerificationProviderResult
from app.model_parameters import ModelParameterConflict, ModelParameterStore
from app.project_delivery_policy import DeliveryPolicyConflict, ProjectDeliveryPolicyStore
from postgresql_support import isolated_postgresql_url
from test_project_business_configuration import MODEL, parameter_values


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class ProjectBusinessPostgreSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._postgres = isolated_postgresql_url("m33_business")
        cls.database_url = cls._postgres.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._postgres.__exit__(None, None, None)

    def setUp(self):
        self.database = DatabaseManager(self.database_url)
        self.project_id = "business-" + os.urandom(5).hex()
        now = datetime.now(timezone.utc)
        with self.database.session() as session:
            session.add(ProjectRecord(project_id=self.project_id, project_code=self.project_id,
                                      display_name=self.project_id, created_at=now, updated_at=now))

    def tearDown(self):
        self.database.close()

    def test_parameters_and_policy_survive_reconnect_with_cas(self):
        store = ModelParameterStore(Path("unused-project-business.json"), self.database)
        values = parameter_values(store)
        values["detection"]["confidenceThreshold"] = 0.51
        store.save(MODEL, "server", values, "owner", 0, self.project_id)
        policy = ProjectDeliveryPolicyStore(self.database)
        policy.save(self.project_id, {"enabled": True, "channels": ["management"],
                                      "minimumSeverity": "MAJOR"}, 0)

        self.database.close()
        self.database = DatabaseManager(self.database_url)
        reopened = ModelParameterStore(Path("unused-project-business.json"), self.database)
        self.assertEqual(reopened.get(MODEL, "server", self.project_id)["revision"], 1)
        self.assertEqual(reopened.get(MODEL, "server", self.project_id)["detection"]["confidenceThreshold"], 0.51)
        with self.assertRaises(ModelParameterConflict):
            reopened.save(MODEL, "server", copy.deepcopy(values), "stale", 0, self.project_id)
        with self.assertRaises(DeliveryPolicyConflict):
            ProjectDeliveryPolicyStore(self.database).save(
                self.project_id, {"enabled": False, "channels": [], "minimumSeverity": "MINOR"}, 0)
        with self.database.session() as session:
            row = session.query(ModelParameterProfileRecord).filter_by(project_id=self.project_id).one()
            self.assertEqual(row.scope, "PROJECT")

    def test_independent_stores_serialize_first_insert_and_updates(self):
        def race(factory, mutate, conflict, expected):
            barrier = Barrier(2)
            stores = [factory(), factory()]
            def worker(store):
                barrier.wait(timeout=10)
                try:
                    mutate(store, expected)
                    return "saved"
                except conflict:
                    return "conflict"
            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertCountEqual(["saved", "conflict"], list(executor.map(worker, stores)))

        values = parameter_values(ModelParameterStore())
        mutations = [
            (lambda: ModelParameterStore(Path("unused-project-business.json"), self.database),
             lambda store, rev: store.save(MODEL, "server", values, "owner", rev, self.project_id), ModelParameterConflict),
            (lambda: ProjectDeliveryPolicyStore(self.database),
             lambda store, rev: store.save(self.project_id, {"enabled": True, "channels": ["management"], "minimumSeverity": "MAJOR"}, rev), DeliveryPolicyConflict),
            (lambda: RuleRegistry(self.database),
             lambda store, rev: store.upsert({"ruleId": "concurrent", "operator": "PRESENCE"}, project_id=self.project_id, expected_revision=rev), RuleConflict),
            (lambda: AlertVerificationStore(database_manager=self.database),
             lambda store, rev: store.configure(enabled=True, image_egress_authorized=True, daily_limit=1, model_id="review", provider_configured=True,
                                                project_id=self.project_id, expected_revision=rev), VerificationConfigConflict),
        ]
        for factory, mutate, conflict in mutations:
            for revision in (0, 1):
                race(factory, mutate, conflict, revision)

        with self.database.session() as session:
            for event_id in ("quota-a", "quota-b"):
                session.add(AlertEventRecord(project_id=self.project_id, event_id=event_id, disposition_status="OPEN", payload={"eventId": event_id}))
        barrier = Barrier(2)
        class Provider:
            def review(self, **kwargs):
                return VerificationProviderResult("CONFIRMED", "fixture")
        def request(event_id):
            store = AlertVerificationStore(database_manager=self.database, provider=Provider())
            barrier.wait(timeout=10)
            return store.request({"eventId": event_id, "projectId": self.project_id}, actor="owner",
                image_ref="image", image_data="data:image/jpeg;base64,aW1hZ2U=", project_id=self.project_id)["failureKind"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual([None, "QUOTA_EXHAUSTED"], list(executor.map(request, ("quota-a", "quota-b"))))
        store = AlertVerificationStore(database_manager=self.database)
        current = store.configure(enabled=True, image_egress_authorized=True, daily_limit=5, model_id="new-review", provider_configured=False,
                                  project_id=self.project_id, expected_revision=2)
        self.assertEqual(1, current["callsToday"])
        with self.assertRaises(VerificationConfigConflict):
            store.configure(enabled=False, image_egress_authorized=False, daily_limit=0, model_id="stale", provider_configured=False,
                            project_id=self.project_id, expected_revision=2)
        self.assertEqual("new-review", store.config(self.project_id)["modelId"])
        self.assertEqual(1, store.config(self.project_id)["callsToday"])

    def test_default_project_platform_and_override_are_separate(self):
        store = ModelParameterStore(Path("unused-project-business.json"), self.database)
        model = {**MODEL, "modelId": "scope-" + self.project_id}
        values = parameter_values(store)
        values["detection"]["confidenceThreshold"] = .4
        store.save(model, "server", values, "admin", 0)
        values["detection"]["confidenceThreshold"] = .52
        store.save(model, "server", values, "owner", 0, DEFAULT_PROJECT_ID)
        with self.database.session() as session:
            rows = session.query(ModelParameterProfileRecord).filter_by(project_id=DEFAULT_PROJECT_ID, model_id=model["modelId"]).all()
            self.assertEqual({"PLATFORM", "PROJECT"}, {row.scope for row in rows})
        store.reset(model, "server", "owner", DEFAULT_PROJECT_ID, 1)
        values["detection"]["confidenceThreshold"] = .5
        store.save(model, "server", values, "admin", 1)
        inherited = store.get(model, "server", DEFAULT_PROJECT_ID)
        self.assertEqual((2, 2, .5), (inherited["revision"], inherited["inheritedRevision"], inherited["detection"]["confidenceThreshold"]))

    def test_migration_preserves_old_project_profile_audit_and_assignment_references(self):
        with isolated_postgresql_url("m33_business_legacy", revision="20261010_07") as url:
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
            command.downgrade(config, "20261010_07")
            db = DatabaseManager(url)
            key = ModelParameterStore._database_profile_key(MODEL["modelId"], MODEL["version"], "server")
            try:
                with db.session() as session:
                    now = datetime.now(timezone.utc)
                    session.add(ProjectRecord(project_id="legacy-business", project_code="legacy-business", display_name="Legacy", created_at=now, updated_at=now))
                    session.flush()
                    session.execute(text("INSERT INTO model_parameter_profiles (project_id, profile_key, model_id, model_version, platform, revision, payload) VALUES ('legacy-business', :key, :model, :version, 'server', 1, '{}'::jsonb)"), {"key": key, "model": MODEL["modelId"], "version": MODEL["version"]})
                    session.execute(text("INSERT INTO model_parameter_audits (project_id, profile_key, action, revision, actor, payload) VALUES ('legacy-business', :key, 'UPDATED', 1, 'owner', '{}'::jsonb)"), {"key": key})
                    session.execute(text("INSERT INTO project_model_assignments (assignment_id, project_id, scenario, model_id, model_version, parameter_profile_key, enabled, revision, created_at, updated_at) VALUES ('legacy-assignment', 'legacy-business', 'ppe', :model, :version, :key, true, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"key": key, "model": MODEL["modelId"], "version": MODEL["version"]})
                command.upgrade(config, "20261012_11")
                with db.session() as session:
                    row = session.get(ModelParameterProfileRecord, ("legacy-business", key))
                    self.assertEqual("PROJECT", row.scope)
                    self.assertEqual(key, session.scalar(text("SELECT parameter_profile_key FROM project_model_assignments WHERE assignment_id = 'legacy-assignment'")))
                    self.assertEqual(key, session.scalar(text("SELECT profile_key FROM model_parameter_audits WHERE project_id = 'legacy-business'")))
                    self.assertFalse(session.scalar(text("SELECT enabled FROM project_model_assignments WHERE assignment_id = 'legacy-assignment'")))
                with self.assertRaisesRegex(RuntimeError, "project parameter overrides exist"):
                    command.downgrade(config, "20261010_07")
                with db.session() as session:
                    self.assertIsNotNone(session.get(ModelParameterProfileRecord, ("legacy-business", key)))
                    # PostgreSQL rolls back the complete failed downgrade,
                    # including intermediate Alembic version updates.
                    self.assertEqual("20261012_11", session.scalar(text("SELECT version_num FROM alembic_version")))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
