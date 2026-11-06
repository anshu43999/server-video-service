import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO

from alembic import command
import sqlalchemy as sa
from starlette.datastructures import Headers

from app import project_auth as authz
from app import project_migration as migration
from app.config import settings
from app.database import DEFAULT_PROJECT_ID
import test_multi_project_migration as legacy_fixture
import test_project_authorization as authorization_fixture
from fastapi.testclient import TestClient
from app.observability import RequestTelemetry
from app.alert_evidence import AlertEvidenceStore


class DefaultProjectRolloutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m33-t14-")
        self.root = Path(self.temp.name)
        self.url = f"sqlite:///{(self.root / 'source.db').as_posix()}"
        self.bundle = self.root / "backup"

    def tearDown(self):
        self.temp.cleanup()

    def seed(self):
        with migration.database_connection(self.url, write=True) as connection:
            command.upgrade(migration.config(connection), migration.LEGACY)
        fixture = legacy_fixture.MultiProjectMigrationTests()
        fixture.url = self.url
        fixture._seed_legacy_rows()

    def prepare(self, **kwargs):
        result = migration.prepare(self.url, self.bundle, **kwargs)
        migration.restore(f"sqlite:///{(self.root / 'preflight-restore.db').as_posix()}",
                          self.bundle, maintenance=True)
        return result

    def test_empty_upgrade_repeat_and_restore(self):
        self.prepare()
        migration.apply(self.url, self.bundle, maintenance=True)
        self.assertEqual("already-applied", migration.apply(self.url, self.bundle, maintenance=True)["phase"])
        destination = f"sqlite:///{(self.root / 'restored.db').as_posix()}"
        migration.restore(destination, self.bundle, maintenance=True)
        with migration.database_connection(destination) as connection:
            self.assertEqual([], sa.inspect(connection).get_table_names())

    def test_all_legacy_tables_mapping_reconcile_and_rollback(self):
        self.seed()
        self.prepare()
        result = migration.apply(self.url, self.bundle, maintenance=True)
        self.assertEqual(2, result["accounts"])
        with migration.database_connection(self.url) as connection:
            migration.reconcile(connection, self.bundle, migration.verify_bundle(self.bundle))
        destination = f"sqlite:///{(self.root / 'restored.db').as_posix()}"
        migration.restore(destination, self.bundle, maintenance=True)
        with migration.database_connection(destination) as connection:
            self.assertEqual(migration.LEGACY, migration.preflight(connection)["revision"])
            self.assertEqual(1, connection.scalar(sa.text("SELECT COUNT(*) FROM alert_events")))
        with self.assertRaisesRegex(migration.MigrationError, "empty"):
            migration.restore(destination, self.bundle, maintenance=True)
        with self.assertRaisesRegex(migration.MigrationError, "in-place"):
            migration.restore(self.url, self.bundle, maintenance=True)

    def test_interrupted_migration_rolls_back_schema_and_retries(self):
        self.seed()
        self.prepare()
        for point in ("after-schema", "before-commit"):
            def fail(phase):
                if phase == point:
                    raise RuntimeError("injected interruption")
            with self.assertRaisesRegex(RuntimeError, "injected"):
                migration.apply(self.url, self.bundle, maintenance=True, fault=fail)
            with migration.database_connection(self.url) as connection:
                self.assertEqual(migration.LEGACY, migration.preflight(connection)["revision"])
        migration.apply(self.url, self.bundle, maintenance=True)
        # Simulate interruption between database commit and checkpoint replacement.
        migration.atomic_json(self.bundle / "checkpoint.json", {"phase": "applying"})
        self.assertEqual("already-applied", migration.apply(self.url, self.bundle, maintenance=True)["phase"])

    def test_corrupt_backup_and_changed_source_fail_closed(self):
        self.seed()
        self.prepare()
        with self.assertRaisesRegex(migration.MigrationError, "maintenance"):
            migration.apply(self.url, self.bundle)
        with migration.database_connection(self.url, write=True) as connection:
            connection.execute(sa.text("UPDATE accounts SET password_hash='changed' WHERE username='admin'"))
        with self.assertRaisesRegex(migration.MigrationError, "source data changed"):
            migration.apply(self.url, self.bundle, maintenance=True)
        with (self.bundle / "accounts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("{}\n")
        with self.assertRaisesRegex(migration.MigrationError, "checksum"):
            migration.verify_bundle(self.bundle)

    def test_local_evidence_backup_survives_original_loss(self):
        self.seed()
        evidence_root = self.root / "files"
        evidence_root.mkdir()
        (evidence_root / "frame.png").write_bytes(b"synthetic-image-bytes")
        with migration.database_connection(self.url, write=True) as connection:
            connection.execute(sa.text("UPDATE alert_events SET payload=:payload"),
                               {"payload": json.dumps({"evidence": {"snapshotUri": "frame.png"}})})
        self.prepare(roots=[evidence_root])
        (evidence_root / "frame.png").unlink()
        migration.apply(self.url, self.bundle, maintenance=True)
        with migration.database_connection(self.url) as connection:
            payload = json.loads(connection.scalar(sa.text("SELECT payload FROM alert_events")))
            self.assertEqual(DEFAULT_PROJECT_ID, payload["projectId"])
            self.assertEqual(b"synthetic-image-bytes", base64.b64decode(payload["evidence"]["snapshotUri"].split(",")[1]))
        destination = f"sqlite:///{(self.root / 'restored-images.db').as_posix()}"
        migration.restore(destination, self.bundle, maintenance=True)
        with migration.database_connection(destination) as connection:
            payload = json.loads(connection.scalar(sa.text("SELECT payload FROM alert_events")))
            self.assertNotIn("projectId", payload)
            self.assertTrue(payload["evidence"]["snapshotUri"].startswith("data:image/png;"))

    def test_orphan_receipts_are_backed_up_restored_but_block_upgrade(self):
        self.seed()
        with migration.database_connection(self.url, write=True) as connection:
            connection.execute(sa.text("UPDATE alert_delivery_receipts SET event_id='missing'"))
        result = self.prepare()
        self.assertEqual([{"code": "orphan_delivery_receipts", "count": 1}], result["blockers"])
        with self.assertRaisesRegex(migration.MigrationError, "preflight blockers"):
            migration.apply(self.url, self.bundle, maintenance=True)
        migration.restore(f"sqlite:///{(self.root / 'orphan-restore.db').as_posix()}", self.bundle, maintenance=True)
        with migration.database_connection(self.url) as connection:
            self.assertEqual(migration.LEGACY, migration.preflight(connection)["revision"])

    def test_opt_in_archive_is_transactional_idempotent_and_fully_restorable(self):
        self.seed()
        with migration.database_connection(self.url, write=True) as connection:
            connection.execute(sa.text("UPDATE alert_delivery_receipts SET event_id='missing'"))
        self.prepare()
        for point in ("after-archive", "after-schema", "before-commit"):
            def fail(phase):
                if phase == point:
                    raise RuntimeError("injected")
            with self.assertRaisesRegex(RuntimeError, "injected"):
                migration.apply(self.url, self.bundle, maintenance=True, archive_orphan_receipts=True, fault=fail)
            with migration.database_connection(self.url) as connection:
                self.assertEqual(1, connection.scalar(sa.text("SELECT COUNT(*) FROM alert_delivery_receipts")))
                self.assertEqual(migration.LEGACY, migration.preflight(connection)["revision"])
        migration.apply(self.url, self.bundle, maintenance=True, archive_orphan_receipts=True)
        self.assertEqual("already-applied", migration.apply(self.url, self.bundle, maintenance=True,
                                                            archive_orphan_receipts=True)["phase"])
        with migration.database_connection(self.url) as connection:
            self.assertEqual(0, connection.scalar(sa.text("SELECT COUNT(*) FROM alert_delivery_receipts")))
            migration.reconcile(connection, self.bundle, migration.verify_bundle(self.bundle))
        destination = f"sqlite:///{(self.root / 'after-migration-restore.db').as_posix()}"
        migration.restore(destination, self.bundle, maintenance=True)
        with migration.database_connection(destination) as connection:
            self.assertEqual("missing", connection.scalar(sa.text("SELECT event_id FROM alert_delivery_receipts")))
        with (self.bundle / f"{migration.ARCHIVE_NAME}.jsonl").open("ab") as handle:
            handle.write(b"{}\n")
        with self.assertRaisesRegex(migration.MigrationError, "archive checksum"):
            migration.verify_bundle(self.bundle)

    def test_cached_evidence_reuses_only_exact_content_bound_references(self):
        self.seed()
        content = b"object-bytes"
        class Response(BytesIO):
            def release_conn(self):
                pass
        class Client:
            def get_object(self, bucket, key):
                return Response(content)
        store = AlertEvidenceStore(endpoint="localhost:9000", access_key="test", secret_key="test", client=Client())
        event_hash = migration.digest(b"event-1")
        reference = {"provider": "minio", "bucket": store.bucket,
                     "objectKey": f"alerts/{event_hash[:2]}/{event_hash}.png", "contentType": "image/png",
                     "sha256": migration.digest(content)}
        with migration.database_connection(self.url, write=True) as connection:
            connection.execute(sa.text("UPDATE alert_events SET payload=:p"),
                               {"p": json.dumps({"evidence": {"objectStorage": reference}})})
        migration.prepare(self.url, self.bundle, store=store)
        with patch.object(store._client, "get_object", side_effect=AssertionError("offline")):
            result = migration.prepare(self.url, self.root / "offline-bundle", store=store, evidence_bundle=self.bundle)
        self.assertEqual(1, result["evidenceReuse"]["count"])
        with migration.database_connection(self.url, write=True) as connection:
            changed = dict(reference, sha256="changed")
            connection.execute(sa.text("UPDATE alert_events SET payload=:p"),
                               {"p": json.dumps({"evidence": {"objectStorage": changed}})})
        with patch.object(store._client, "get_object", side_effect=RuntimeError("network required")):
            with self.assertRaisesRegex(RuntimeError, "network required"):
                migration.prepare(self.url, self.root / "changed-bundle", store=store, evidence_bundle=self.bundle)

    def test_object_checksum_ownership_and_backup_recovery(self):
        self.seed()
        content = b"synthetic-object-image"
        class Response(BytesIO):
            def release_conn(self):
                pass
        class Client:
            def get_object(self, bucket, key):
                return Response(content)
        store = AlertEvidenceStore(endpoint="localhost:9000", access_key="test", secret_key="test", client=Client())
        event_hash = migration.digest(b"event-1")
        reference = {"provider": "minio", "bucket": store.bucket,
                     "objectKey": f"alerts/{event_hash[:2]}/{event_hash}.png", "contentType": "image/png",
                     "sha256": migration.digest(content)}
        with migration.database_connection(self.url, write=True) as connection:
            connection.execute(sa.text("UPDATE alert_events SET payload=:p"), {"p": json.dumps({"evidence": {
                "snapshotUri": "/aiyoloapi/alerts/event-1/evidence", "objectStorage": reference}})})
        self.prepare(store=store)
        migration.apply(self.url, self.bundle, maintenance=True)
        wrong = dict(reference, objectKey="alerts/aa/another-project.png")
        assets = migration.Assets(self.bundle, store=store)
        with self.assertRaisesRegex(migration.MigrationError, "ownership"):
            assets.read_source(wrong, "event-1")
        with self.assertRaisesRegex(migration.MigrationError, "checksum"):
            assets.read_source(dict(reference, sha256="bad"), "event-1")
        checksum = next(iter(migration.verify_bundle(self.bundle)["assets"].values()))["sha256"]
        (self.bundle / "assets" / checksum).write_bytes(b"tampered")
        with self.assertRaisesRegex(migration.MigrationError, "checksum"):
            migration.verify_bundle(self.bundle)

    def test_missing_foreign_and_remote_evidence_refused(self):
        self.seed()
        for index, reference in enumerate(("missing.png", "../outside.png", "https://example.test/secret.png")):
            with migration.database_connection(self.url, write=True) as connection:
                connection.execute(sa.text("UPDATE alert_events SET payload=:payload"),
                                   {"payload": json.dumps({"evidence": {"snapshotUri": reference}})})
            with self.assertRaises(migration.MigrationError):
                migration.prepare(self.url, self.root / f"bad-{index}", roots=[self.root])

    def test_requires_restore_and_rejects_schema_drift(self):
        self.seed()
        migration.prepare(self.url, self.bundle)
        with self.assertRaisesRegex(migration.MigrationError, "first restore"):
            migration.apply(self.url, self.bundle, maintenance=True)
        migration.restore(f"sqlite:///{(self.root / 'verified.db').as_posix()}", self.bundle, maintenance=True)
        with migration.database_connection(self.url, write=True) as connection:
            connection.execute(sa.text("CREATE INDEX custom_account_index ON accounts(enabled)"))
        with self.assertRaisesRegex(migration.MigrationError, "schema changed"):
            migration.apply(self.url, self.bundle, maintenance=True)

    def test_old_evidence_cache_can_be_reused_but_not_applied(self):
        self.seed()
        self.prepare()
        manifest = migration.verify_bundle(self.bundle)
        manifest["format"] = 1
        migration.atomic_json(self.bundle / "manifest.json", manifest)
        migration.atomic_json(self.bundle / "manifest.sha256.json", {
            "sha256": migration.digest((self.bundle / "manifest.json").read_bytes())
        })
        self.assertFalse(migration.summary(migration.verify_bundle(self.bundle), "backup-verified")["applyReady"])
        with self.assertRaisesRegex(migration.MigrationError, "evidence-only"):
            migration.apply(self.url, self.bundle, maintenance=True)


class LegacyWindowTests(unittest.TestCase):
    def test_http_fallback_keeps_authorization_revocation_and_safe_warnings(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with patch.object(authz.auth.database, "url", None), patch.object(settings, "legacy_project_id", DEFAULT_PROJECT_ID), patch.object(settings, "legacy_project_until", future), patch.object(settings, "deployment_env", "development"):
            authz.auth.reset_memory_auth_for_tests()
            authz.reset_memory_project_authorization_for_tests()
            app = authorization_fixture.create_test_app()
            app.add_middleware(RequestTelemetry)
            with TestClient(app) as client:
                response = client.post("/aiyoloapi/auth/setup", json={"username": "admin", "password": "correct-horse-1"})
                headers = {"Authorization": "Bearer " + response.json()["accessToken"]}
                account = client.get("/aiyoloapi/auth/me", headers=headers).json()["accountId"]
                authz.set_memory_project(DEFAULT_PROJECT_ID, "legacy-default")
                authz.auth.update_memory_account_for_tests(account, platform_role="NORMAL_USER")
                self.assertEqual(404, client.get("/compat/project", headers=headers).status_code)
                authz.set_memory_membership(DEFAULT_PROJECT_ID, account, authz.PROJECT_USER)
                with self.assertLogs("aiyolo.requests", level="WARNING") as captured:
                    response = client.get("/compat/project?token=must-not-log", headers=headers)
                self.assertEqual(200, response.status_code)
                self.assertIn("299", response.headers["warning"])
                self.assertIn("GMT", response.headers["sunset"])
                self.assertNotIn("must-not-log", "".join(captured.output))
                self.assertIn(response.headers["x-request-id"], "".join(captured.output))
                authz.remove_memory_membership(DEFAULT_PROJECT_ID, account)
                self.assertEqual(404, client.get("/compat/project", headers=headers).status_code)
                authz.set_memory_project("second", "second")
                self.assertEqual(400, client.get("/compat/project", headers=headers).status_code)
            authz.auth.reset_memory_auth_for_tests()
            authz.reset_memory_project_authorization_for_tests()

    def test_window_expiry_wrong_mapping_and_second_project(self):
        scope = type("Scope", (), {"path_params": {}, "headers": Headers()})()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with patch.object(authz.auth.database, "url", None), patch.object(settings, "legacy_project_id", DEFAULT_PROJECT_ID), patch.object(settings, "legacy_project_until", future):
            authz.reset_memory_project_authorization_for_tests()
            authz.set_memory_project(DEFAULT_PROJECT_ID, "legacy-default")
            with self.assertLogs("aiyolo.requests", level="WARNING"):
                self.assertEqual(DEFAULT_PROJECT_ID, authz._project_id(scope))
            with patch.object(settings, "legacy_project_until", "2000-01-01T00:00:00Z"):
                with self.assertRaises(authz.HTTPException):
                    authz._project_id(scope)
            with patch.object(settings, "legacy_project_until", (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()):
                with self.assertRaises(authz.HTTPException):
                    authz._project_id(scope)
            authz.set_memory_project("other", "other")
            with self.assertRaises(authz.HTTPException):
                authz._project_id(scope)
            scope.headers = Headers({"x-project-id": "other"})
            self.assertEqual("other", authz._project_id(scope))
            authz.reset_memory_project_authorization_for_tests()


if __name__ == "__main__":
    unittest.main()
