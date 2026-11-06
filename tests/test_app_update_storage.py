"""Run the same durable constraints against migrated SQLite and PostgreSQL."""
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.app_updates.models import (TABLES, AppIdentity, AppArtifact, AppArtifactSource,
    AppPolicy, AppRelease, AppPolicyRevision, AppRollback, AppDeviceState, AppReceipt, AppAudit)
from postgresql_support import isolated_postgresql_url

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)
PACKAGE = "com.aiyolo.inspection"


def migration_config(url):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


class StorageAssertions:
    def seed(self):
        with Session(self.engine) as session, session.begin():
            session.add(AppIdentity(package_name=PACKAGE, publisher_id="enterprise-primary"))
            session.flush()
            session.add(AppArtifact(artifact_id="apk-2", package_name=PACKAGE,
                publisher_id="enterprise-primary", state="verified", version_code=2, version_name="0.1.1",
                size_bytes=100, sha256="a" * 64, signer_sha256="b" * 64, min_sdk=27,
                abis=["arm64-v8a"], server_contract_min=1, server_contract_max=1,
                data_schema_version=19, readable_schema_min=18, readable_schema_max=19,
                verification_evidence_ref="evidence/test/apk-2", verified_at=NOW, created_by="admin"))
            session.add(AppPolicy(policy_id="policy", package_name=PACKAGE, publisher_id="enterprise-primary",
                channel="enterprise-stable", deployment_id="test", updated_by="admin"))
            session.flush()
            session.add(AppArtifactSource(source_id="source", artifact_id="apk-2", source_revision=1,
                storage_mode="external", access_mode="public", public_url="https://apk.example.com/2",
                allowed_hosts=["apk.example.com"], state="verified", verified_sha256="a" * 64,
                verified_size_bytes=100, verified_at=NOW, verification_evidence_ref="evidence/test/source", created_by="admin"))
            session.add(AppRelease(release_id="release", policy_id="policy", package_name=PACKAGE,
                publisher_id="enterprise-primary", artifact_id="apk-2", state="published", published_at=NOW,
                created_by="admin"))
            session.add(AppDeviceState(policy_id="policy", installation_id="device", current_version_code=1))

    def rejected(self, record):
        with self.assertRaises(IntegrityError):
            with Session(self.engine) as session, session.begin():
                session.add(record)
                session.flush()

    def receipt(self, **changes):
        values = dict(policy_id="policy", installation_id="device", event_id="event", attempt_id="attempt",
            sequence=1, release_id="release", artifact_id="apk-2", source_id="source", source_revision=1,
            policy_revision=1, stage="downloaded", from_version_code=1, target_version_code=2,
            observed_version_code=1, occurred_at=NOW, request_sha256="c" * 64)
        return AppReceipt(**(values | changes))

    def test_migration_rerun_and_model_ddl_match(self):
        command.upgrade(self.config, "head")
        inspector = inspect(self.engine)
        for model in TABLES:
            table = model.__table__
            with self.subTest(table=table.name):
                self.assertEqual(set(table.columns.keys()), {c["name"] for c in inspector.get_columns(table.name)})
                self.assertEqual({c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"},
                                 {c["name"] for c in inspector.get_check_constraints(table.name)})
        with self.engine.connect() as connection:
            self.assertEqual("20261029_29", connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())

    def test_dual_sources_roundtrip_and_restart(self):
        self.seed()
        with Session(self.engine) as session, session.begin():
            session.add(AppArtifactSource(source_id="minio", artifact_id="apk-2", source_revision=2,
                storage_mode="internal", access_mode="presigned", bucket="apks", object_key="sha256/2.apk",
                credential_config_ref="app-apks", created_by="admin"))
            session.add(self.receipt())
            session.add(AppPolicyRevision(policy_id="policy", revision=1, snapshot={"releaseId": "release"},
                snapshot_sha256="d" * 64, key_id="test", payload_base64url="e30", signature_base64url="A" * 86, created_by="admin"))
        self.engine.dispose()
        with Session(self.engine) as session:
            self.assertEqual(2, len(session.scalars(select(AppArtifactSource)).all()))
            self.assertEqual("downloaded", session.get(AppReceipt, ("policy", "device", "event")).stage)
            self.assertEqual({"releaseId": "release"}, session.get(AppPolicyRevision, ("policy", 1)).snapshot)

    def test_duplicate_global_version_and_wrong_identity_rejected(self):
        self.seed()
        self.rejected(AppArtifact(artifact_id="duplicate", package_name=PACKAGE, publisher_id="enterprise-primary",
                                  version_code=2, created_by="admin"))
        self.rejected(AppArtifact(artifact_id="wrong", package_name=PACKAGE, publisher_id="other", created_by="admin"))
        self.rejected(AppIdentity(package_name="com.other.app", publisher_id="enterprise-primary"))
        self.rejected(AppArtifact(artifact_id="zero", package_name=PACKAGE, publisher_id="enterprise-primary", version_code=0, created_by="admin"))

    def test_verified_requires_evidence_and_source_location(self):
        self.seed()
        self.rejected(AppArtifact(artifact_id="bad", package_name=PACKAGE, publisher_id="enterprise-primary", state="verified", created_by="admin"))
        for change in ({"public_url": "http://apk.example.com/2"}, {"access_mode": "presigned"},
                       {"bucket": "leak"}, {"state": "verified"}):
            values = dict(source_id="bad", artifact_id="apk-2", source_revision=2, storage_mode="external",
                          access_mode="public", public_url="https://apk.example.com/2", created_by="admin")
            self.rejected(AppArtifactSource(**(values | change)))

    def test_receipt_idempotency_stage_and_scoped_references(self):
        self.seed()
        with Session(self.engine) as session, session.begin():
            session.add(self.receipt())
        self.rejected(self.receipt())
        self.rejected(self.receipt(event_id="different"))  # attempt sequence uniqueness
        for change in ({"stage": "healthy"}, {"source_revision": 2}, {"artifact_id": "unknown"},
                       {"policy_id": "other"}, {"stage": "installed"}, {"stage": "failed"},
                       {"source_id": None}, {"target_version_code": 1}):
            self.rejected(self.receipt(**({"event_id": "bad", "sequence": 2} | change)))
        with Session(self.engine) as session, session.begin():
            session.add(self.receipt(event_id="healthy", sequence=2, stage="healthy", observed_version_code=2))

    def test_policy_cas_and_rollback_idempotency(self):
        self.seed()
        with self.engine.begin() as connection:
            sql = text("UPDATE app_update_policies SET revision = revision + 1 WHERE policy_id = 'policy' AND revision = :expected")
            self.assertEqual(1, connection.execute(sql, {"expected": 1}).rowcount)
            self.assertEqual(0, connection.execute(sql, {"expected": 1}).rowcount)
        values = dict(operation_id="rollback", policy_id="policy", idempotency_key="one",
            request_sha256="e" * 64, preview_fingerprint="f" * 64, expected_policy_revision=2,
            affected_release_ids=["release"], stable_release_id="release", actor_id="admin", reason="faulty build")
        with Session(self.engine) as session, session.begin():
            session.add(AppRollback(**values))
        self.rejected(AppRollback(**(values | {"operation_id": "duplicate"})))
        self.rejected(AppRollback(**(values | {"operation_id": "bad", "idempotency_key": "two", "state": "applied"})))
        self.rejected(AppRollback(**(values | {"operation_id": "bad", "idempotency_key": "two", "recovery_state": "ready"})))

    def test_audit_history_and_cross_scope_release_are_guarded(self):
        self.seed()
        with Session(self.engine) as session, session.begin():
            session.add(AppPolicy(policy_id="other", package_name=PACKAGE, publisher_id="enterprise-primary",
                channel="enterprise-stable", deployment_id="other-deployment", updated_by="admin"))
            audit = dict(audit_id="audit", policy_id="policy", actor_id="admin", action="publish",
                resource_id="release", idempotency_key="one", request_sha256="a" * 64,
                before_revision=1, after_revision=2, reason="publish verified APK", result="succeeded")
            session.add(AppAudit(**audit))
        self.rejected(AppAudit(**(audit | {"audit_id": "duplicate"})))
        # Same installation ID in a different deployment cannot refer to this
        # deployment's release, even though all string identifiers exist.
        with Session(self.engine) as session, session.begin():
            session.add(AppDeviceState(policy_id="other", installation_id="device", current_version_code=1))
        self.rejected(self.receipt(policy_id="other"))

    def test_references_restrict_delete_and_data_refuses_downgrade(self):
        self.seed()
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text("DELETE FROM app_artifacts WHERE artifact_id = 'apk-2'"))
        with self.assertRaisesRegex(RuntimeError, "durable history"):
            command.downgrade(self.config, "20261027_26")
        # T03's empty migration can be rolled back before T01 refuses the
        # historical downgrade; all existing business records remain intact.
        self.assertTrue(set(m.__tablename__ for m in TABLES if m.__tablename__ != "app_apk_uploads").issubset(inspect(self.engine).get_table_names()))

    def test_empty_downgrade_then_upgrade(self):
        command.downgrade(self.config, "20261027_26")
        self.assertTrue(set(m.__tablename__ for m in TABLES).isdisjoint(inspect(self.engine).get_table_names()))
        command.upgrade(self.config, "head")
        self.assertTrue(set(m.__tablename__ for m in TABLES).issubset(inspect(self.engine).get_table_names()))


class AppUpdateSQLiteTest(StorageAssertions, unittest.TestCase):
    def setUp(self):
        (ROOT / ".test-db").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="app-update-", dir=ROOT / ".test-db")
        self.url = "sqlite+pysqlite:///" + (Path(self.temp.name) / "test.db").as_posix()
        self.config = migration_config(self.url)
        command.upgrade(self.config, "head")
        self.engine = create_engine(self.url)
        @event.listens_for(self.engine, "connect")
        def sqlite_fk(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.engine.dispose)


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires disposable PostgreSQL")
class AppUpdatePostgreSQLTest(StorageAssertions, unittest.TestCase):
    def setUp(self):
        self.cluster = isolated_postgresql_url("app_update")
        self.url = self.cluster.__enter__()
        self.config = migration_config(self.url)
        self.engine = create_engine(self.url)
        self.addCleanup(lambda: self.cluster.__exit__(None, None, None))
        self.addCleanup(self.engine.dispose)
