import json
import unittest

from app.alerts.disposition import AlertDispositionStore, sanitise_training_entry


class AlertDispositionTests(unittest.TestCase):
    def setUp(self):
        self.store = AlertDispositionStore()
        self.store.register({
            "eventId": "evt-1", "ruleId": "helmet", "ruleVersion": 2,
            "sourceId": "cam-1", "subjectKey": "track:7", "confirmedAtUs": 123,
            "effectiveThresholds": {"minConfidence": 0.8},
            "evidence": {"snapshotUri": r"C:\secret\evidence\frame.jpg"},
            "detectionResults": [{"label": "object", "confidence": 0.9}],
            "disposition": {"status": "OPEN"},
        })

    def test_acknowledge_records_actor_time_and_history(self):
        event = self.store.dispose("evt-1", "ACKNOWLEDGED", "operator-7", acted_at_us=456)
        self.assertEqual(event["disposition"]["status"], "ACKNOWLEDGED")
        self.assertEqual(event["disposition"]["actor"], "operator-7")
        self.assertEqual(event["disposition"]["actedAtUs"], 456)
        self.assertEqual(event["disposition"]["history"][0]["status"], "ACKNOWLEDGED")
        self.assertEqual(self.store.feedback(), [])

    def test_false_positive_exports_training_entry_without_absolute_path(self):
        event = self.store.dispose("evt-1", "FALSE_POSITIVE", "reviewer", acted_at_us=789,
                                   screenshot=r"C:\secret\evidence\false.jpg",
                                   detection_results=[{"bbox": [1, 2, 3, 4]}])
        self.assertEqual(event["state"], "ENDED")
        payload = json.loads(self.store.export_json())
        self.assertEqual(payload["format"], "aiyolo-false-positive-v1")
        self.assertEqual(len(payload["entries"]), 1)
        entry = payload["entries"][0]
        self.assertEqual(entry["image"], "evidence/false.jpg")
        self.assertNotIn("C:\\secret", json.dumps(payload))
        self.assertEqual(entry["effectiveThresholds"]["minConfidence"], 0.8)

    def test_sanitizer_redacts_secret_keys_and_paths(self):
        result = sanitise_training_entry({"token": "do-not-export", "path": "/var/run/frame.jpg"})
        self.assertNotIn("do-not-export", json.dumps(result))
        self.assertEqual(result["path"], "evidence/frame.jpg")

    def test_missing_event_and_invalid_status_are_explicit(self):
        with self.assertRaises(KeyError):
            self.store.get("missing")
        with self.assertRaises(ValueError):
            self.store.dispose("evt-1", "UNKNOWN", "operator")


if __name__ == "__main__":
    unittest.main()
