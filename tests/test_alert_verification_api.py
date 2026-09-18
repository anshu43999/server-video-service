import unittest

from fastapi.testclient import TestClient

from app.alerts.disposition import alert_disposition_store
from app.alerts.verification import alert_verification_store
from app.config import settings
from app.main import app


class AlertVerificationApiTests(unittest.TestCase):
    def setUp(self):
        self.old_database = alert_disposition_store.database_manager
        alert_disposition_store.configure_database(None)
        self.old_admin, self.old_mobile = settings.admin_token, settings.mobile_token
        settings.admin_token, settings.mobile_token = "admin-secret", "mobile-secret"
        alert_disposition_store.reset()
        alert_verification_store.reset()
        alert_verification_store.enabled = True
        alert_verification_store.image_egress_authorized = True
        alert_verification_store.daily_limit = 3
        alert_disposition_store.register({
            "eventId": "evt-review", "ruleId": "helmet", "sourceId": "cam",
            "subjectKey": "track:1", "evidence": {"snapshotUri": "/srv/evidence/frame.jpg"},
            "disposition": {"status": "OPEN"},
        })
        self.client = TestClient(app)

    def tearDown(self):
        settings.admin_token, settings.mobile_token = self.old_admin, self.old_mobile
        alert_disposition_store.reset()
        alert_disposition_store.configure_database(self.old_database)
        alert_verification_store.reset()

    def test_manual_request_is_deduplicated_and_keeps_disposition(self):
        headers = {"X-Admin-Token": "admin-secret", "X-Operator-Id": "reviewer"}
        first = self.client.post("/api/alerts/evt-review/verification", headers=headers, json={})
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["status"], "FAILED")
        self.assertEqual(first.json()["failureKind"], "NOT_CONFIGURED")
        second = self.client.post("/api/alerts/evt-review/verification", headers=headers, json={})
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json()["requestedAtUs"], first.json()["requestedAtUs"])
        event = self.client.get("/api/alerts/evt-review", headers={"X-Admin-Token": "admin-secret"}).json()
        self.assertEqual(event["disposition"]["status"], "OPEN")
        self.assertEqual(event["verification"]["failureKind"], "NOT_CONFIGURED")

    def test_privacy_gate_is_fail_closed(self):
        alert_verification_store.image_egress_authorized = False
        response = self.client.post(
            "/api/alerts/evt-review/verification",
            headers={"X-Admin-Token": "admin-secret", "X-Operator-Id": "reviewer"},
            json={},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["failureKind"], "NOT_AUTHORIZED")


if __name__ == "__main__":
    unittest.main()
