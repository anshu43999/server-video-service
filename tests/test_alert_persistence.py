import unittest
import uuid
from pathlib import Path

from app.alerts.disposition import AlertDispositionStore
from app.database import Base, DatabaseManager


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


if __name__ == "__main__":
    unittest.main()
