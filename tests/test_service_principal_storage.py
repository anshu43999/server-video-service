from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from threading import Barrier
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import event, select, text
from starlette.requests import Request

from app import auth
from app.alerts.disposition import AlertDispositionStore
from app.database import (AccountRecord, Base, DatabaseManager, ProjectAuditEventRecord,
    ProjectRecord, ServicePrincipalRecord, ServiceRequestNonceRecord)
from app.project_auth import resolve_project_context
from app.service_principals import (ALERTS_INGEST, STREAMS_INGEST, PrincipalCreate,
    PrincipalPatch, PrincipalRevision, PrincipalRotate, create_principal, list_principals,
    mutate_principal, principal_audits, resolve_service_context)
from postgresql_support import isolated_postgresql_url


class StorageChecks:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = DatabaseManager(getattr(self, "database_url", f"sqlite:///{Path(self.temp.name).as_posix()}/credential.db"))
        self.addCleanup(self.db.close)
        if self.db.backend == "sqlite":
            event.listen(self.db.engine, "connect", lambda connection, record: connection.execute("PRAGMA foreign_keys=ON"))
            Base.metadata.create_all(self.db.engine)
        self.patch = patch("app.auth.database", self.db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.account_id = str(uuid4())
        self.project_id = str(uuid4())
        self.other_id = str(uuid4())
        with self.db.session() as session:
            session.add(AccountRecord(account_id=self.account_id, username="admin-" + self.account_id, password_hash="not-a-password", role="admin", platform_role="PLATFORM_ADMIN", enabled=True))
            session.flush()
            for pid in [self.project_id, self.other_id]:
                session.add(ProjectRecord(project_id=pid, project_code="project-" + pid, display_name=pid, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
        self.context = resolve_project_context(auth._principal(self.account_id, "admin", "PLATFORM_ADMIN"), self.project_id)

    def create(self):
        return create_principal(PrincipalCreate(displayName="device", principalType="SERVICE", capabilities=[ALERTS_INGEST], expiresAt=datetime.now(timezone.utc)+timedelta(hours=1)), self.context, "create-request")

    def scope(self, value, nonce=None, project_id=None):
        return Request({"type": "http", "method": "POST", "path": "/ingest",
            "path_params": {"project_id": project_id or self.project_id},
            "headers": [(b"authorization", ("Bearer "+value["credential"]).encode()),
                (b"x-service-timestamp", str(int(time.time())).encode()),
                (b"x-service-nonce", (nonce or uuid4().hex).encode())]})

    def test_digest_persistence_usage_audit_and_no_account_fk_impersonation(self):
        value = self.create()
        context = resolve_service_context(self.scope(value), ALERTS_INGEST)
        self.assertIsNone(context.principal.account_id)
        self.db.close()
        listed = list_principals(self.project_id)
        self.assertEqual(1, len(listed))
        self.assertIsNotNone(listed[0]["lastUsedAt"])
        self.assertNotIn("credential", str(listed))
        self.assertEqual([], list_principals(self.other_id))
        audits = principal_audits(self.project_id, value["principalId"], 0, 100)
        self.assertEqual({"service_principal.create", "service_principal.use"}, {a["action"] for a in audits})
        self.assertNotIn(value["credential"], str(audits))
        with self.db.session() as session:
            row = session.get(ServicePrincipalRecord, value["principalId"])
            self.assertEqual(64, len(row.credential_digest))
            self.assertNotEqual(value["credential"], row.credential_digest)
            audit = session.scalar(select(ProjectAuditEventRecord).where(ProjectAuditEventRecord.actor_service_principal_id == value["principalId"]))
            self.assertIsNone(audit.actor_account_id)
            self.assertEqual(self.project_id, audit.project_id)

    def test_nonce_survives_restart_and_rejects_replay_without_touching_last_use(self):
        value = self.create()
        scope = self.scope(value)
        resolve_service_context(scope, ALERTS_INGEST)
        previous = list_principals(self.project_id)[0]["lastUsedAt"]
        self.db.close()
        with self.assertRaises(HTTPException) as exc:
            resolve_service_context(scope, ALERTS_INGEST)
        self.assertEqual(409, exc.exception.status_code)
        self.assertEqual(previous, list_principals(self.project_id)[0]["lastUsedAt"])
        with self.db.session() as session:
            self.assertEqual(1, len(session.scalars(select(ServiceRequestNonceRecord).where(ServiceRequestNonceRecord.principal_id == value["principalId"])).all()))
        denied = [a for a in principal_audits(self.project_id, value["principalId"], 0, 100) if a["outcome"] == "DENIED"]
        self.assertEqual("service_request_replayed", denied[0]["failureCode"])

    def test_rotation_revocation_current_capability_expiry_and_cross_project(self):
        value = self.create()
        pid = value["principalId"]
        rotated = mutate_principal(pid, PrincipalRotate(expectedRevision=1, expiresAt=value["expiresAt"]), self.context, "rotate", "rotate")
        with self.assertRaises(HTTPException) as error:
            resolve_service_context(self.scope(value), ALERTS_INGEST)
        self.assertEqual(401, error.exception.status_code)
        resolve_service_context(self.scope(rotated), ALERTS_INGEST)
        with self.assertRaises(HTTPException) as error:
            resolve_service_context(self.scope(rotated, project_id=self.other_id), ALERTS_INGEST)
        self.assertEqual(404, error.exception.status_code)
        mutate_principal(pid, PrincipalPatch(expectedRevision=2, capabilities=[STREAMS_INGEST]), self.context, "patch", "update")
        with self.assertRaises(HTTPException) as error:
            resolve_service_context(self.scope(rotated), ALERTS_INGEST)
        self.assertEqual(403, error.exception.status_code)
        with self.db.session() as session:
            session.get(ServicePrincipalRecord, pid).expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        with self.assertRaises(HTTPException) as error:
            resolve_service_context(self.scope(rotated), STREAMS_INGEST)
        self.assertEqual(401, error.exception.status_code)
        mutate_principal(pid, PrincipalRevision(expectedRevision=3), self.context, "revoke", "revoke")
        self.db.close()
        self.assertIsNotNone(list_principals(self.project_id)[0]["revokedAt"])
        with self.assertRaises(HTTPException) as error:
            mutate_principal(pid, PrincipalRotate(expectedRevision=4, expiresAt=value["expiresAt"]), self.context, "rotate", "rotate")
        self.assertEqual(409, error.exception.status_code)

    def test_project_state_enforced_from_current_database(self):
        value = self.create()
        for state in ["SUSPENDED", "ARCHIVED"]:
            with self.db.session() as session:
                session.get(ProjectRecord, self.project_id).lifecycle_state = state
            with self.assertRaises(HTTPException) as error:
                resolve_service_context(self.scope(value), ALERTS_INGEST)
            self.assertEqual(403, error.exception.status_code)

    def test_service_event_is_immutable_and_preserves_human_disposition(self):
        value = self.create()
        event = {"eventId": f"service:{value['principalId']}:1", "servicePrincipalId": value["principalId"],
                 "serviceIngestDigest": "canonical-digest", "state": "CONFIRMED"}
        store = AlertDispositionStore(self.db)
        self.assertTrue(store.register_service_once(event, self.project_id, service_revision=1)[1])
        store.dispose(event["eventId"], "ACKNOWLEDGED", self.account_id, project_id=self.project_id)
        self.assertFalse(store.register_service_once(event, self.project_id, service_revision=1)[1])
        with self.assertRaisesRegex(ValueError, "service_event_conflict"):
            store.register_service_once({**event, "serviceIngestDigest": "tampered"}, self.project_id, service_revision=1)
        self.assertEqual("ACKNOWLEDGED", store.get(event["eventId"], self.project_id)["disposition"]["status"])
        self.assertEqual([], store.list(project_id=self.other_id))

    def test_event_transaction_rejects_credential_changes_after_preflight(self):
        value = self.create()
        context = resolve_service_context(self.scope(value), ALERTS_INGEST)
        event = {"eventId": f"service:{value['principalId']}:late", "servicePrincipalId": value["principalId"],
                 "serviceIngestDigest": "digest", "state": "CONFIRMED"}
        mutate_principal(value["principalId"], PrincipalRevision(expectedRevision=1), self.context, "revoke", "revoke")
        store = AlertDispositionStore(self.db)
        with self.assertRaises(HTTPException) as exc:
            store.register_service_once(event, self.project_id, service_revision=context.principal.revision)
        self.assertEqual(401, exc.exception.status_code)
        self.assertEqual([], store.list(project_id=self.project_id))


class ServicePrincipalSqliteTests(StorageChecks, unittest.TestCase):
    pass


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL schema")
class ServicePrincipalPostgreSqlTests(StorageChecks, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.postgres = isolated_postgresql_url("m33_credentials")
        cls.database_url = cls.postgres.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.postgres.__exit__(None, None, None)

    def test_concurrent_rotation_cas_without_process_lock(self):
        value = self.create()
        barrier = Barrier(2)
        def worker(_):
            barrier.wait(timeout=10)
            try:
                return mutate_principal(value["principalId"], PrincipalRotate(expectedRevision=1, expiresAt=value["expiresAt"]), self.context, "race", "rotate")
            except HTTPException as exc:
                return exc.status_code
        with patch("app.service_principals._lock", nullcontext()):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(worker, range(2)))
        self.assertEqual(1, results.count(409))
        winner = next(item for item in results if isinstance(item, dict))
        resolve_service_context(self.scope(winner), ALERTS_INGEST)
        with self.assertRaises(HTTPException):
            resolve_service_context(self.scope(value), ALERTS_INGEST)

    def test_concurrent_replay_nonce_and_event_first_write_without_process_lock(self):
        value = self.create()
        scope = self.scope(value)
        barrier = Barrier(2)
        def authenticate(_):
            barrier.wait(timeout=10)
            try:
                resolve_service_context(scope, ALERTS_INGEST)
                return 200
            except HTTPException as exc:
                return exc.status_code
        with patch("app.service_principals._lock", nullcontext()):
            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertCountEqual([200, 409], list(executor.map(authenticate, range(2))))
        barrier = Barrier(2)
        def ingest(index):
            barrier.wait(timeout=10)
            store = AlertDispositionStore(self.db)
            event = {"eventId": f"service:{value['principalId']}:race", "servicePrincipalId": value["principalId"], "serviceIngestDigest": str(index)}
            try:
                store.register_service_once(event, self.project_id, service_revision=1)
                return 200
            except ValueError:
                return 409
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual([200, 409], list(executor.map(ingest, range(2))))

    def test_migration_idempotence_metadata_and_principal_downgrade_guard(self):
        with isolated_postgresql_url("m33_credential_migration", revision="20261012_09") as url:
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
            command.downgrade(config, "20261012_09")
            command.upgrade(config, "20261012_11")
            command.upgrade(config, "20261012_11")
            command.check(config)
            db = DatabaseManager(url)
            try:
                with db.session() as session:
                    session.add(AccountRecord(account_id="migration-admin", username="migration-admin", password_hash="hash", role="admin", platform_role="PLATFORM_ADMIN", enabled=True))
                    session.flush()
                    session.add(ServicePrincipalRecord(principal_id="migration-principal", project_id="00000000-0000-0000-0000-000000000001", display_name="machine", principal_type="DEVICE", capabilities=[ALERTS_INGEST], credential_digest="a"*64, expires_at=datetime.now(timezone.utc), revision=1, created_by_account_id="migration-admin"))
                with self.assertRaisesRegex(RuntimeError, "principals exist"):
                    command.downgrade(config, "20261012_09")
                with db.session() as session:
                    self.assertEqual("20261012_11", session.scalar(text("SELECT version_num FROM alembic_version")))
                    self.assertIsNotNone(session.get(ServicePrincipalRecord, "migration-principal"))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
