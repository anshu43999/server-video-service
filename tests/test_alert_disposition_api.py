import unittest

from fastapi.testclient import TestClient

from app.main import app, settings
from app.alerts.disposition import alert_disposition_store


class AlertDispositionApiTests(unittest.TestCase):
    def setUp(self):
        self.old_admin, self.old_mobile = settings.admin_token, settings.mobile_token
        settings.admin_token, settings.mobile_token = "admin-secret", "mobile-secret"
        alert_disposition_store.reset()
        alert_disposition_store.register({
            "eventId": "evt-api", "ruleId": "r1", "sourceId": "cam", "subjectKey": "track:1",
            "confirmedAtUs": 100, "effectiveThresholds": {"minConfidence": .8},
            "evidence": {"snapshotUri": "/srv/evidence/frame.jpg"},
            "detectionResults": [{"label": "x"}], "disposition": {"status": "OPEN"},
        })
        self.client = TestClient(app)

    def tearDown(self):
        settings.admin_token, settings.mobile_token = self.old_admin, self.old_mobile
        alert_disposition_store.reset()

    def test_mobile_can_read_but_cannot_dispose(self):
        response = self.client.get("/api/alerts", headers={"X-Video-Service-Token": "mobile-secret"})
        self.assertEqual(response.status_code, 200)
        denied = self.client.post("/api/alerts/evt-api/acknowledge", headers={"X-Video-Service-Token": "mobile-secret"}, json={})
        self.assertEqual(denied.status_code, 403)

    def test_admin_disposition_and_safe_export(self):
        response = self.client.post(
            "/api/alerts/evt-api/false-positive",
            headers={"X-Admin-Token": "admin-secret", "X-Operator-Id": "reviewer"},
            json={"actedAtUs": 200, "screenshot": "C:\\private\\frame.jpg"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["disposition"]["status"], "FALSE_POSITIVE")
        exported = self.client.get("/api/alerts/false-positives/export", headers={"X-Video-Service-Token": "mobile-secret"})
        self.assertEqual(exported.status_code, 200)
        self.assertNotIn("C:\\private", exported.text)
        self.assertIn("evidence/frame.jpg", exported.text)


if __name__ == "__main__":
    unittest.main()
