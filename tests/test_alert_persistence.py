import unittest
import uuid
from pathlib import Path

from app.alerts.disposition import AlertDispositionStore
from app.database import Base, DatabaseManager, FalsePositiveFeedbackRecord
from sqlalchemy import select


class AlertPersistenceTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / ".test-db"
        test_root.mkdir(exist_ok=True)
        self.path = test_root / f"alerts-{uuid.uuid4().hex}.db"
        self.url = f"sqlite+pysqlite:///{self.path.as_posix()}"
        self.database = DatabaseManager(self.url)
        Base.metadata.create_all(self.database.engine)
        self.store = AlertDispositionStore(self.database)

    def tearDown(self):
        self.database.close()
        self.path.unlink(missing_ok=True)

    @staticmethod
    def event():
        return {
            "eventId": "local:helmet:PPE_NO_HELMET:1",
            "ruleId": "PPE_NO_HELMET",
            "sourceId": "image:现场拍照",
            "subjectKey": "frame:1",
            "state": "CONFIRMED",
            "severity": "MAJOR",
            "effectiveThresholds": {"minimumConfidence": 0.75},
            "detectionResults": [{"label": "head", "confidence": 0.91}],
            "evidence": {"snapshotUri": "evidence/one.png"},
        }

    def test_event_and_acknowledgement_survive_store_recreation(self):
        self.store.register(self.event())
        self.store.dispose("local:helmet:PPE_NO_HELMET:1", "ACKNOWLEDGED", "operator", acted_at_us=2000)
        self.database.close()

        reopened_database = DatabaseManager(self.url)
        reopened = AlertDispositionStore(reopened_database)
        event = reopened.get("local:helmet:PPE_NO_HELMET:1")
        self.assertEqual(event["disposition"]["status"], "ACKNOWLEDGED")
        self.assertEqual(event["effectiveThresholds"]["minimumConfidence"], 0.75)
        self.assertEqual(event["detectionResults"][0]["label"], "head")
        reopened_database.close()

    def test_duplicate_disposition_is_idempotent_and_false_positive_is_terminal(self):
        self.store.register(self.event())
        first = self.store.dispose(
            "local:helmet:PPE_NO_HELMET:1",
            "FALSE_POSITIVE",
            "operator",
            acted_at_us=3000,
        )
        second = self.store.dispose(
            "local:helmet:PPE_NO_HELMET:1",
            "FALSE_POSITIVE",
            "operator",
            acted_at_us=3000,
        )
        self.assertEqual(first["state"], "ENDED")
        self.assertEqual(len(second["disposition"]["history"]), 1)
        self.assertEqual(len(self.store.feedback()), 1)
        self.assertEqual(len(self.store.list(status="FALSE_POSITIVE")), 1)

    def test_reset_cannot_clear_persistent_database(self):
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            self.store.reset()

    def test_source_name_snapshot_survives_reopen_and_feedback(self):
        provenance = {"kind": "SCENE", "scene": {"sceneId": "scene-02", "name": "场景02", "revision": 3},
                      "plan": {"planId": "plan-1", "name": "联合相机方案"}, "memberId": "helmet-member",
                      "model": {"modelId": "uploaded-06abc", "name": "安全帽", "version": "2.0.0"}}
        event = {**self.event(), "provenance": provenance, "model": provenance["model"]}
        self.store.register(event)
        self.store.dispose(event["eventId"], "FALSE_POSITIVE", "operator", acted_at_us=3000)
        reopened_db = DatabaseManager(self.url)
        try:
            reopened = AlertDispositionStore(reopened_db)
            self.assertEqual(provenance, reopened.get(event["eventId"])["provenance"])
            self.assertEqual(provenance, reopened.feedback()[0]["provenance"])
        finally:
            reopened_db.close()

    def test_late_evidence_repairs_persisted_feedback_without_image_bytes(self):
        event = self.event()
        event['evidence'] = {}
        event_id = event['eventId']
        self.store.register(event)
        self.store.dispose(event_id, 'FALSE_POSITIVE', 'operator', acted_at_us=4000)
        project_id = self.store.get(event_id)['projectId']
        self.assertEqual(self.store.feedback()[0]['evidenceUnavailableReason'], 'evidence_not_uploaded')
        reference = {'sha256': 'a' * 64, 'objectStorage': {'provider': 'minio', 'objectKey': 'test/image.jpg'}}
        self.store.register_evidence(event_id, project_id, 'original', 2, reference)
        with self.database.session() as session:
            stored = session.scalar(select(FalsePositiveFeedbackRecord)).payload
            self.assertTrue(stored['image'].endswith('/evidence/original/2'))
            self.assertIsNone(stored['evidenceUnavailableReason'])
        reopened_database = DatabaseManager(self.url)
        try:
            entry = AlertDispositionStore(reopened_database).feedback()[0]
            self.assertEqual(entry['image'], stored['image'])
        finally:
            reopened_database.close()


if __name__ == "__main__":
    unittest.main()
