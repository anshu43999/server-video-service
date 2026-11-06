import os
import unittest
import uuid
import time
import hashlib
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.main as main_module
from app.alerts.disposition import AlertDispositionStore, alert_disposition_store
from app.config import settings
from app.database import AlertEventRecord, DatabaseManager, ProjectRecord, FalsePositiveFeedbackRecord, DEFAULT_PROJECT_ID
from app.alerts.evidence_retention import cleanup_alert_evidence
from app.alert_evidence import AlertEvidenceStore
from app.main import app
from app.project_auth import reset_memory_project_authorization_for_tests
from app.project_management import reset_memory_project_management_for_tests
from postgresql_support import isolated_postgresql_url


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class AlertPostgreSqlIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._postgres = isolated_postgresql_url("m33_alert")
        cls.database_url = cls._postgres.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._postgres.__exit__(None, None, None)

    @staticmethod
    def event(event_id):
        return {
            "eventId": event_id,
            "ruleId": "PPE_NO_HELMET",
            "sourceId": "integration-test",
            "subjectKey": "frame:1",
            "state": "CONFIRMED",
            "severity": "MAJOR",
            "effectiveThresholds": {"minimumConfidence": 0.8},
            "detectionResults": [{"label": "head", "confidence": 0.91}],
            "evidence": {"snapshotUri": "evidence/integration.png"},
        }

    def test_event_and_false_positive_survive_new_connection(self):
        self.assertIsNotNone(settings.database_url)
        event_id = f"integration:postgres:m29t03:{uuid.uuid4().hex}"
        first_database = DatabaseManager(self.database_url)
        try:
            first_database.verify_schema()
            first = AlertDispositionStore(first_database)
            first.register(self.event(event_id))
            first.dispose(event_id, "FALSE_POSITIVE", "integration-test", acted_at_us=123456)
            first_database.close()

            reopened_database = DatabaseManager(self.database_url)
            reopened = AlertDispositionStore(reopened_database)
            event = reopened.get(event_id)
            self.assertEqual(event["disposition"]["status"], "FALSE_POSITIVE")
            self.assertEqual(len(event["disposition"]["history"]), 1)
            self.assertEqual(len([item for item in reopened.feedback() if item["eventId"] == event_id]), 1)
            reopened_database.close()
        finally:
            cleanup = DatabaseManager(self.database_url)
            with cleanup.session() as session:
                session.execute(delete(AlertEventRecord).where(AlertEventRecord.event_id == event_id))
            cleanup.close()

    def test_v1_concurrent_first_insert_returns_one_creator_and_preserves_identity(self):
        event_id = f"local:v1-race:{uuid.uuid4().hex}"
        provenance = {"kind": "SCENE", "scene": {"sceneId": "s2", "name": "场景02", "revision": 3},
                      "plan": {"planId": "p1", "name": "联合相机方案"}, "memberId": "m1",
                      "model": {"modelId": "uploaded-06abc", "name": "安全帽", "version": "2.0.0"}}
        event = {**self.event(event_id), "startedAtUs": 1000, "evidence": {}, "provenance": provenance}

        def register(source):
            database = DatabaseManager(self.database_url)
            try:
                return AlertDispositionStore(database).register_mobile_fact(
                    {**event, "sourceId": source}, DEFAULT_PROJECT_ID)
            finally:
                database.close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(register, ["integration-test"] * 8))
        self.assertEqual(1, sum(created for _, created in results))
        with self.assertRaisesRegex(ValueError, "event_identity_conflict"):
            register("conflicting-source")
        database = DatabaseManager(self.database_url)
        try:
            store = AlertDispositionStore(database)
            store.register_evidence(event_id, DEFAULT_PROJECT_ID, "thumbnail", 1,
                {"type": "thumbnail", "sha256": "a" * 64, "objectStorage": {"provider": "minio"}})
            store.dispose(event_id, "ACKNOWLEDGED", "integration-test", acted_at_us=2000)
            item, created = store.register_mobile_fact(event, DEFAULT_PROJECT_ID)
            self.assertFalse(created)
            self.assertEqual("ACKNOWLEDGED", item["disposition"]["status"])
            self.assertEqual("a" * 64, item["evidence"]["thumbnail"]["1"]["sha256"])
            self.assertEqual(provenance, item["provenance"])
            with self.assertRaisesRegex(ValueError, "event_identity_conflict"):
                store.register_mobile_fact({**event, "provenance": {**provenance, "memberId": "other"}}, DEFAULT_PROJECT_ID)
        finally:
            database.close()

    def test_ingest_cannot_reset_a_concurrent_disposition(self):
        self.assertIsNotNone(settings.database_url)
        event_id = f"integration:postgres:m29t04-race:{uuid.uuid4().hex}"
        seed_database = DatabaseManager(self.database_url)
        try:
            AlertDispositionStore(seed_database).register(self.event(event_id))
        finally:
            seed_database.close()

        def ingest_retry():
            database = DatabaseManager(self.database_url)
            try:
                return AlertDispositionStore(database).register(self.event(event_id))
            finally:
                database.close()

        def mark_false_positive():
            database = DatabaseManager(self.database_url)
            try:
                return AlertDispositionStore(database).dispose(
                    event_id, "FALSE_POSITIVE", "race-reviewer", acted_at_us=987654,
                )
            finally:
                database.close()

        try:
            with ThreadPoolExecutor(max_workers=8) as workers:
                futures = [workers.submit(ingest_retry) for _ in range(6)]
                futures.append(workers.submit(mark_false_positive))
                for future in futures:
                    future.result()

            reopened_database = DatabaseManager(self.database_url)
            reopened = AlertDispositionStore(reopened_database)
            event = reopened.get(event_id)
            self.assertEqual(event["disposition"]["status"], "FALSE_POSITIVE")
            self.assertEqual(event["state"], "ENDED")
            self.assertEqual(len(event["disposition"]["history"]), 1)
            reopened_database.close()
        finally:
            cleanup = DatabaseManager(self.database_url)
            with cleanup.session() as session:
                session.execute(delete(AlertEventRecord).where(AlertEventRecord.event_id == event_id))
            cleanup.close()

    def test_inline_feedback_is_sanitized_in_persistent_rows_and_after_reopen(self):
        event_id = f"integration:m37:inline:{uuid.uuid4().hex}"
        inline = "data:image/png;base64,c2VjcmV0LWltYWdlLWJ5dGVz"
        database = DatabaseManager(self.database_url)
        try:
            store = AlertDispositionStore(database)
            event = self.event(event_id)
            event["evidence"] = {"snapshotUri": inline}
            store.register(event)
            store.dispose(event_id, "FALSE_POSITIVE", "integration-reviewer", acted_at_us=555,
                          detection_results=[{"image": inline, "bytes": b"raw-image"}])
            with database.session() as session:
                feedback = session.scalar(select(FalsePositiveFeedbackRecord).where(
                    FalsePositiveFeedbackRecord.project_id == DEFAULT_PROJECT_ID,
                    FalsePositiveFeedbackRecord.event_id == event_id,
                ))
                self.assertNotIn("data:image", str(feedback.payload))
                self.assertNotIn("raw-image", str(feedback.payload))
                self.assertIn("/aiyoloapi/projects/", feedback.payload["image"])
                self.assertEqual(session.get(AlertEventRecord, (DEFAULT_PROJECT_ID, event_id))
                                 .payload["evidence"]["snapshotUri"], inline)
            reopened_database = DatabaseManager(self.database_url)
            try:
                entries = AlertDispositionStore(reopened_database).feedback()
                selected = next(entry for entry in entries if entry["eventId"] == event_id)
                self.assertNotIn("data:image", str(selected))
                self.assertTrue(selected["image"].endswith("/evidence"))
            finally:
                reopened_database.close()
        finally:
            with database.session() as session:
                session.execute(delete(AlertEventRecord).where(AlertEventRecord.event_id == event_id))
            database.close()

    def test_concurrent_ingest_and_disposition_are_idempotent(self):
        self.assertIsNotNone(settings.database_url)
        event_id = f"integration:postgres:m29t04:{uuid.uuid4().hex}"

        def with_store(callback):
            database = DatabaseManager(self.database_url)
            try:
                return callback(AlertDispositionStore(database))
            finally:
                database.close()

        try:
            with ThreadPoolExecutor(max_workers=6) as workers:
                registrations = list(workers.map(
                    lambda _: with_store(lambda store: store.register(self.event(event_id))),
                    range(6),
                ))
            self.assertEqual({item["eventId"] for item in registrations}, {event_id})

            with ThreadPoolExecutor(max_workers=6) as workers:
                dispositions = list(workers.map(
                    lambda _: with_store(lambda store: store.dispose(
                        event_id, "FALSE_POSITIVE", "concurrent-reviewer", acted_at_us=456789,
                    )),
                    range(6),
                ))
            self.assertTrue(all(item["disposition"]["status"] == "FALSE_POSITIVE" for item in dispositions))

            reopened_database = DatabaseManager(self.database_url)
            reopened = AlertDispositionStore(reopened_database)
            event = reopened.get(event_id)
            self.assertEqual(len(event["disposition"]["history"]), 1)
            self.assertEqual(len([item for item in reopened.feedback() if item["eventId"] == event_id]), 1)
            reopened_database.close()
        finally:
            cleanup = DatabaseManager(self.database_url)
            with cleanup.session() as session:
                session.execute(delete(AlertEventRecord).where(AlertEventRecord.event_id == event_id))
            cleanup.close()

    def test_retention_waits_for_event_lock_and_reader_sees_tombstone(self):
        """A cleaner must re-read the locked payload after waiting for a writer."""
        event_id = f"integration:postgres:m37-retention:{uuid.uuid4().hex}"
        project_id = "retention-isolated-project"
        now = datetime.now(timezone.utc)
        object_key = f"alerts/test-only/{uuid.uuid4().hex}.png"
        payload = {
            "eventId": event_id, "projectId": project_id,
            "evidence": {"thumbnail": {"1": {
                "uploadedAt": (now - timedelta(days=120)).isoformat(),
                "retentionState": "DELETE_PENDING",
                "deleteAfter": (now - timedelta(hours=1)).isoformat(),
                "objectStorage": {"provider": "minio", "bucket": "isolated-test", "objectKey": object_key},
            }}},
        }
        seed = DatabaseManager(self.database_url)
        with seed.session() as session:
            session.add(ProjectRecord(
                project_id=project_id, project_code=f"retention-{uuid.uuid4().hex[:12]}",
                display_name="Retention isolated test", lifecycle_state="ACTIVE",
            ))
            session.flush()
            session.add(AlertEventRecord(project_id=project_id, event_id=event_id, payload=payload))
        seed.close()

        class Store:
            enabled = True
            bucket = "isolated-test"
            removed = []

            def remove_tiered(self, reference):
                self.removed.append(reference["objectKey"])

        store = Store()
        blocker = DatabaseManager(self.database_url)
        connection = blocker.engine.connect()
        transaction = connection.begin()
        connection.execute(select(AlertEventRecord).where(
            AlertEventRecord.project_id == project_id,
            AlertEventRecord.event_id == event_id,
        ).with_for_update()).first()

        def clean():
            database = DatabaseManager(self.database_url)
            try:
                return cleanup_alert_evidence(database, store, apply=True, now=now)
            finally:
                database.close()

        try:
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(clean)
                time.sleep(0.2)
                self.assertFalse(future.done(), "cleaner should wait for the event row lock")
                transaction.commit()
                result = future.result(timeout=10)
            self.assertEqual(result["deleted"], 1)
            self.assertEqual(store.removed, [object_key])

            reader_db = DatabaseManager(self.database_url)
            reader = AlertDispositionStore(reader_db)
            with self.assertRaises(KeyError):
                reader.read_evidence(event_id, project_id, "thumbnail", 1, lambda ref: ref)
            with reader_db.session() as session:
                row = session.get(AlertEventRecord, (project_id, event_id))
                ref = row.payload["evidence"]["thumbnail"]["1"]
                self.assertEqual(ref["retentionState"], "DELETED")
                self.assertNotIn("objectStorage", ref)
            reader_db.close()
        finally:
            if transaction.is_active:
                transaction.rollback()
            connection.close()
            blocker.close()
            cleanup_db = DatabaseManager(self.database_url)
            with cleanup_db.session() as session:
                session.execute(delete(AlertEventRecord).where(
                    AlertEventRecord.project_id == project_id,
                    AlertEventRecord.event_id == event_id,
                ))
                session.execute(delete(ProjectRecord).where(ProjectRecord.project_id == project_id))
            cleanup_db.close()

    @unittest.skipUnless(os.environ.get("RUN_MINIO_RETENTION_TESTS") == "1",
                         "set RUN_MINIO_RETENTION_TESTS=1 for real MinIO retention test")
    def test_real_minio_retention_round_trip_removes_only_unique_test_object(self):
        event_id = f"integration:postgres:minio-retention:{uuid.uuid4().hex}"
        project_id = str(uuid.uuid4())
        store = AlertEvidenceStore.from_settings(settings)
        self.assertTrue(store.enabled, "configured remote MinIO is required")
        store.validate()
        now = datetime.now(timezone.utc)
        content = b"\x89PNG\r\n\x1a\n" + uuid.uuid4().bytes
        digest = hashlib.sha256(content).hexdigest()
        object_storage = store.store_tiered_bytes(
            project_id, event_id, "thumbnail", 1, content, "image/png", digest,
        )
        key = object_storage["objectKey"]
        database = DatabaseManager(self.database_url)
        try:
            with database.session() as session:
                session.add(ProjectRecord(
                    project_id=project_id, project_code=f"mr-{uuid.uuid4().hex[:12]}",
                    display_name="MinIO retention isolated test", lifecycle_state="ACTIVE",
                ))
                session.flush()
                session.add(AlertEventRecord(
                    project_id=project_id, event_id=event_id,
                    payload={"eventId": event_id, "projectId": project_id, "evidence": {
                        "thumbnail": {"1": {"uploadedAt": (now - timedelta(days=120)).isoformat(),
                            "retentionState": "ACTIVE", "sha256": digest,
                            "objectStorage": object_storage}}
                    }},
                ))

            preview = cleanup_alert_evidence(database, store, now=now, retention_days=90)
            self.assertEqual(preview["marked"], 1)
            self.assertEqual(store._client.get_object(store.bucket, key).read(), content)
            marked = cleanup_alert_evidence(database, store, apply=True, now=now, retention_days=90)
            self.assertEqual(marked["marked"], 1)
            with database.session() as session:
                row = session.get(AlertEventRecord, (project_id, event_id))
                delete_after = datetime.fromisoformat(
                    row.payload["evidence"]["thumbnail"]["1"]["deleteAfter"]
                )
            removed = cleanup_alert_evidence(
                database, store, apply=True, now=delete_after + timedelta(seconds=1), retention_days=90,
            )
            self.assertEqual(removed["deleted"], 1)
            with self.assertRaises(Exception):
                store._client.stat_object(store.bucket, key)
            with database.session() as session:
                ref = session.get(AlertEventRecord, (project_id, event_id)).payload[
                    "evidence"]["thumbnail"]["1"]
                self.assertEqual(ref["retentionState"], "DELETED")
                self.assertNotIn("objectStorage", ref)
        except Exception:
            # Best-effort cleanup is constrained to this run's unique object key.
            try:
                store.remove_tiered(object_storage)
            except Exception:
                pass
            raise
        finally:
            with database.session() as session:
                session.execute(delete(AlertEventRecord).where(
                    AlertEventRecord.project_id == project_id,
                    AlertEventRecord.event_id == event_id,
                ))
                session.execute(delete(ProjectRecord).where(ProjectRecord.project_id == project_id))
            database.close()

    def test_mobile_and_admin_api_round_trip_through_postgresql(self):
        acknowledged_id = f"integration:postgres:m29t04-api-ack:{uuid.uuid4().hex}"
        false_positive_id = f"integration:postgres:m29t04-api-fp:{uuid.uuid4().hex}"
        old_database = alert_disposition_store.database_manager
        old_delivery_database = main_module.alert_delivery.database_manager
        old_settings = (settings.deployment_env, settings.admin_token, settings.mobile_token)
        integration_database = DatabaseManager(self.database_url)
        alert_disposition_store.configure_database(integration_database)
        main_module.alert_delivery.configure_database(integration_database)
        settings.deployment_env = "production"
        settings.admin_token = None
        settings.mobile_token = None

        def payload(event_id, status):
            value = self.event(event_id)
            value.update({
                "label": "head",
                "notifySeverity": "MAJOR",
                "startedAtUs": 1000,
                "confirmedAtUs": 1000,
                "lastSeenAtUs": 1000,
                "disposition": {
                    "status": status,
                    "actor": "device-operator",
                    "actedAtUs": 2000 if status == "ACKNOWLEDGED" else 3000,
                },
            })
            return value

        try:
            with ExitStack() as isolation:
                isolation.enter_context(patch("app.auth.database", integration_database))
                reset_memory_project_authorization_for_tests()
                reset_memory_project_management_for_tests()
                client = TestClient(app)
                try:
                    setup = client.post(
                        "/aiyoloapi/auth/setup",
                        json={
                            "username": "postgres-alert-admin",
                            "password": "temporary-test-password",
                        },
                    )
                    self.assertEqual(200, setup.status_code, setup.text)
                    headers = {
                        "Authorization": f"Bearer {setup.json()['accessToken']}"
                    }
                    account_id = client.get(
                        "/aiyoloapi/auth/me", headers=headers
                    ).json()["accountId"]
                    project = client.post(
                        "/aiyoloapi/projects",
                        headers=headers,
                        json={
                            "projectCode": "postgres-alert",
                            "displayName": "PostgreSQL Alert",
                            "ownerAccountId": account_id,
                        },
                    )
                    self.assertEqual(201, project.status_code, project.text)
                    project_id = project.json()["projectId"]
                    alerts_path = f"/aiyoloapi/projects/{project_id}/alerts"

                    first = client.post(
                        f"{alerts_path}/mobile-ingest", headers=headers,
                        json=payload(acknowledged_id, "ACKNOWLEDGED"),
                    )
                    retry = client.post(
                        f"{alerts_path}/mobile-ingest", headers=headers,
                        json=payload(acknowledged_id, "ACKNOWLEDGED"),
                    )
                    false_positive = client.post(
                        f"{alerts_path}/mobile-ingest", headers=headers,
                        json=payload(false_positive_id, "FALSE_POSITIVE"),
                    )
                    self.assertEqual(202, first.status_code, first.text)
                    self.assertEqual(202, retry.status_code, retry.text)
                    self.assertEqual(202, false_positive.status_code, false_positive.text)
                    self.assertEqual(
                        1, len(retry.json()["event"]["disposition"]["history"])
                    )
                    self.assertEqual(
                        account_id,
                        retry.json()["event"]["disposition"]["actor"],
                    )

                    filtered = client.get(
                        f"{alerts_path}?status=ACKNOWLEDGED", headers=headers
                    )
                    self.assertEqual(200, filtered.status_code, filtered.text)
                    self.assertIn(
                        acknowledged_id,
                        {item["eventId"] for item in filtered.json()["events"]},
                    )
                    exported = client.get(
                        f"{alerts_path}/false-positives/export", headers=headers
                    )
                    self.assertEqual(200, exported.status_code, exported.text)
                    self.assertIn(false_positive_id, exported.text)

                    reopened_database = DatabaseManager(self.database_url)
                    try:
                        alert_disposition_store.configure_database(reopened_database)
                        detail = client.get(
                            f"{alerts_path}/{acknowledged_id}", headers=headers
                        )
                        self.assertEqual(200, detail.status_code, detail.text)
                        self.assertEqual(
                            "ACKNOWLEDGED",
                            detail.json()["disposition"]["status"],
                        )
                    finally:
                        alert_disposition_store.configure_database(integration_database)
                        reopened_database.close()
                finally:
                    client.close()
        finally:
            reset_memory_project_authorization_for_tests()
            reset_memory_project_management_for_tests()
            alert_disposition_store.configure_database(old_database)
            main_module.alert_delivery.configure_database(old_delivery_database)
            integration_database.close()
            settings.deployment_env, settings.admin_token, settings.mobile_token = old_settings


if __name__ == "__main__":
    unittest.main()
