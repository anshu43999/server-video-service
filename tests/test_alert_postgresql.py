import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.alerts.disposition import AlertDispositionStore, alert_disposition_store
from app.config import settings
from app.database import AlertDeliveryReceiptRecord, AlertEventRecord, DatabaseManager
from app.main import app


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class AlertPostgreSqlIntegrationTests(unittest.TestCase):
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
        first_database = DatabaseManager(settings.database_url)
        try:
            first_database.verify_schema()
            first = AlertDispositionStore(first_database)
            first.register(self.event(event_id))
            first.dispose(event_id, "FALSE_POSITIVE", "integration-test", acted_at_us=123456)
            first_database.close()

            reopened_database = DatabaseManager(settings.database_url)
            reopened = AlertDispositionStore(reopened_database)
            event = reopened.get(event_id)
            self.assertEqual(event["disposition"]["status"], "FALSE_POSITIVE")
            self.assertEqual(len(event["disposition"]["history"]), 1)
            self.assertEqual(len([item for item in reopened.feedback() if item["eventId"] == event_id]), 1)
            reopened_database.close()
        finally:
            cleanup = DatabaseManager(settings.database_url)
            with cleanup.session() as session:
                session.execute(delete(AlertEventRecord).where(AlertEventRecord.event_id == event_id))
            cleanup.close()

    def test_ingest_cannot_reset_a_concurrent_disposition(self):
        self.assertIsNotNone(settings.database_url)
        event_id = f"integration:postgres:m29t04-race:{uuid.uuid4().hex}"
        seed_database = DatabaseManager(settings.database_url)
        try:
            AlertDispositionStore(seed_database).register(self.event(event_id))
        finally:
            seed_database.close()

        def ingest_retry():
            database = DatabaseManager(settings.database_url)
            try:
                return AlertDispositionStore(database).register(self.event(event_id))
            finally:
                database.close()

        def mark_false_positive():
            database = DatabaseManager(settings.database_url)
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

            reopened_database = DatabaseManager(settings.database_url)
            reopened = AlertDispositionStore(reopened_database)
            event = reopened.get(event_id)
            self.assertEqual(event["disposition"]["status"], "FALSE_POSITIVE")
            self.assertEqual(event["state"], "ENDED")
            self.assertEqual(len(event["disposition"]["history"]), 1)
            reopened_database.close()
        finally:
            cleanup = DatabaseManager(settings.database_url)
            with cleanup.session() as session:
                session.execute(delete(AlertEventRecord).where(AlertEventRecord.event_id == event_id))
            cleanup.close()

    def test_concurrent_ingest_and_disposition_are_idempotent(self):
        self.assertIsNotNone(settings.database_url)
        event_id = f"integration:postgres:m29t04:{uuid.uuid4().hex}"

        def with_store(callback):
            database = DatabaseManager(settings.database_url)
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

            reopened_database = DatabaseManager(settings.database_url)
            reopened = AlertDispositionStore(reopened_database)
            event = reopened.get(event_id)
            self.assertEqual(len(event["disposition"]["history"]), 1)
            self.assertEqual(len([item for item in reopened.feedback() if item["eventId"] == event_id]), 1)
            reopened_database.close()
        finally:
            cleanup = DatabaseManager(settings.database_url)
            with cleanup.session() as session:
                session.execute(delete(AlertEventRecord).where(AlertEventRecord.event_id == event_id))
            cleanup.close()

    def test_mobile_and_admin_api_round_trip_through_postgresql(self):
        self.assertIsNotNone(settings.database_url)
        acknowledged_id = f"integration:postgres:m29t04-api-ack:{uuid.uuid4().hex}"
        false_positive_id = f"integration:postgres:m29t04-api-fp:{uuid.uuid4().hex}"
        event_ids = [acknowledged_id, false_positive_id]
        old_database = alert_disposition_store.database_manager
        old_admin, old_mobile = settings.admin_token, settings.mobile_token
        integration_database = DatabaseManager(settings.database_url)
        alert_disposition_store.configure_database(integration_database)
        settings.admin_token, settings.mobile_token = "integration-admin", "integration-mobile"
        client = TestClient(app)

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

        mobile_headers = {"X-Video-Service-Token": "integration-mobile"}
        admin_headers = {"X-Admin-Token": "integration-admin"}
        try:
            first = client.post(
                "/api/alerts/mobile-ingest", headers=mobile_headers,
                json=payload(acknowledged_id, "ACKNOWLEDGED"),
            )
            retry = client.post(
                "/api/alerts/mobile-ingest", headers=mobile_headers,
                json=payload(acknowledged_id, "ACKNOWLEDGED"),
            )
            false_positive = client.post(
                "/api/alerts/mobile-ingest", headers=mobile_headers,
                json=payload(false_positive_id, "FALSE_POSITIVE"),
            )
            self.assertEqual(first.status_code, 202)
            self.assertEqual(retry.status_code, 202)
            self.assertEqual(false_positive.status_code, 202)
            self.assertEqual(len(retry.json()["event"]["disposition"]["history"]), 1)

            filtered = client.get("/api/alerts?status=ACKNOWLEDGED", headers=admin_headers)
            self.assertEqual(filtered.status_code, 200)
            self.assertIn(acknowledged_id, {item["eventId"] for item in filtered.json()["events"]})
            exported = client.get("/api/alerts/false-positives/export", headers=admin_headers)
            self.assertEqual(exported.status_code, 200)
            self.assertIn(false_positive_id, exported.text)

            integration_database.close()
            reopened_database = DatabaseManager(settings.database_url)
            alert_disposition_store.configure_database(reopened_database)
            detail = client.get(f"/api/alerts/{acknowledged_id}", headers=admin_headers)
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["disposition"]["status"], "ACKNOWLEDGED")
            reopened_database.close()
        finally:
            client.close()
            cleanup = DatabaseManager(settings.database_url)
            with cleanup.session() as session:
                session.execute(delete(AlertDeliveryReceiptRecord).where(
                    AlertDeliveryReceiptRecord.event_id.in_(event_ids)
                ))
                session.execute(delete(AlertEventRecord).where(AlertEventRecord.event_id.in_(event_ids)))
            cleanup.close()
            settings.admin_token, settings.mobile_token = old_admin, old_mobile
            alert_disposition_store.configure_database(old_database)


if __name__ == "__main__":
    unittest.main()
