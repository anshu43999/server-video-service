import json
import unittest
from pathlib import Path

from app.alerts.disposition import AlertDispositionStore, public_training_entry, sanitise_training_entry


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

    def test_legacy_evidence_paths_do_not_duplicate_evidence_directory(self):
        self.store.register({
            "eventId": "evt-legacy-path",
            "evidence": {"snapshotUri": r"C:\archive\evidence\frame.jpg"},
            "disposition": {"status": "OPEN"},
        })
        self.store.dispose("evt-legacy-path", "FALSE_POSITIVE", "reviewer", acted_at_us=790)
        entry = self.store.feedback()[0]
        self.assertEqual(entry["image"], "evidence/frame.jpg")
        self.assertNotIn("evidence/evidence/", json.dumps(entry))

    def test_data_url_becomes_authenticated_evidence_reference_in_feedback(self):
        data_url = "data:image/png;base64,c2VjcmV0LWltYWdlLWJ5dGVz"
        self.store.register({
            "eventId": "evt-inline-image", "evidence": {"snapshotUri": data_url},
            "disposition": {"status": "OPEN"},
        }, project_id="project-a")
        self.store.dispose("evt-inline-image", "FALSE_POSITIVE", "reviewer", acted_at_us=791,
                           project_id="project-a")
        entry = self.store.feedback("project-a")[0]
        self.assertEqual(entry["image"],
                         "/aiyoloapi/projects/project-a/alerts/evt-inline-image/evidence")
        self.assertNotIn("data:image", json.dumps(entry))
        self.assertNotIn("secret-image-bytes", json.dumps(entry))

    def test_missing_event_and_invalid_status_are_explicit(self):
        with self.assertRaises(KeyError):
            self.store.get("missing")
        with self.assertRaises(ValueError):
            self.store.dispose("evt-1", "UNKNOWN", "operator")

    def test_public_feedback_preserves_specific_absence_reason_until_image_arrives(self):
        entry = {"eventId": "missing", "image": None,
                 "evidenceUnavailableReason": "evidence_deleted"}
        self.assertEqual(public_training_entry(entry, "project-a")["evidenceUnavailableReason"],
                         "evidence_deleted")
        entry["image"] = "/aiyoloapi/projects/project-a/alerts/missing/evidence/original/2"
        self.assertIsNone(public_training_entry(entry, "project-a")["evidenceUnavailableReason"])

    def test_old_reference_fixture_and_service_endpoint_round_trip(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/m37-evidence-references.json").read_text())
        for index, case in enumerate(fixture["cases"]):
            with self.subTest(reference=case["reference"]):
                store = AlertDispositionStore()
                event_id = fixture["eventId"]
                store.register({"eventId": event_id, "origin": "SERVER_STREAM",
                                "evidence": {"snapshotUri": case["reference"]}}, project_id="project-a")
                store.dispose(event_id, "FALSE_POSITIVE", "reviewer", acted_at_us=index,
                              project_id="project-a")
                entry = store.feedback("project-a")[0]
                expected = f"/aiyoloapi/projects/project-a/alerts/{event_id}/evidence" if case.get("canonical") else case["expected"]
                self.assertEqual(entry["image"], expected)
                self.assertEqual(entry["image"], entry["screenshot"])
                self.assertNotIn("DO_NOT_EXPORT", json.dumps(entry))
                self.assertNotIn("data:image", json.dumps(entry))

    def test_tiered_only_feedback_uses_original_reference_and_missing_reason(self):
        self.store.register({"eventId": "tiered", "evidence": {"original": {"2": {
            "objectStorage": {"provider": "minio"}, "retentionState": "ACTIVE"
        }}}})
        self.store.dispose("tiered", "FALSE_POSITIVE", "reviewer", acted_at_us=900)
        ref = self.store.feedback()[0]
        self.assertTrue(ref["image"].endswith("/evidence/original/2"))
        self.assertIsNone(ref["evidenceUnavailableReason"])
        store = AlertDispositionStore()
        store.register({"eventId": "no-evidence"})
        store.dispose("no-evidence", "FALSE_POSITIVE", "reviewer", acted_at_us=901)
        self.assertIsNone(store.feedback()[0]["image"])
        self.assertEqual(store.feedback()[0]["evidenceUnavailableReason"], "evidence_not_uploaded")


if __name__ == "__main__":
    unittest.main()
