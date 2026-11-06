import unittest

from fastapi.testclient import TestClient

from app.alerts.disposition import alert_disposition_store
from app.alerts.verification import alert_verification_store
from app.config import settings
from app.main import app
from project_api_support import ProjectApiSupport


class AlertVerificationApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.old_database = alert_disposition_store.database_manager
        alert_disposition_store.configure_database(None)
        alert_disposition_store.reset()
        self.old_verification_database = alert_verification_store.database_manager
        alert_verification_store.configure_database(None)
        alert_verification_store.reset()
        self.start_project_api("verification-project")
        alert_verification_store.configure(
            enabled=True,
            image_egress_authorized=True,
            daily_limit=3,
            model_id="",
            provider_configured=False,
            project_id=self.project_id,
        )
        alert_disposition_store.register({
            "eventId": "evt-review", "ruleId": "helmet", "sourceId": "cam",
            "subjectKey": "track:1", "evidence": {"snapshotUri": "/srv/evidence/frame.jpg"},
            "disposition": {"status": "OPEN"},
        }, project_id=self.project_id)

    def tearDown(self):
        alert_disposition_store.reset()
        alert_disposition_store.configure_database(self.old_database)
        alert_verification_store.reset()
        alert_verification_store.configure_database(self.old_verification_database)
        self.stop_project_api()

    def test_manual_request_is_retired_and_does_not_annotate_the_alert(self):
        first = self.client.post(
            f"{self.project_path}/alerts/evt-review/verification",
            headers={**self.headers, "X-Actor": "forged-reviewer"},
        )
        self.assertEqual(first.status_code, 410)
        self.assertEqual(first.json()["detail"]["code"], "verification_retired")
        event = self.client.get(
            f"{self.project_path}/alerts/evt-review", headers=self.headers
        ).json()
        self.assertEqual(event["disposition"]["status"], "OPEN")
        self.assertNotIn("verification", event)

    def test_review_configuration_is_retired_without_deleting_existing_data(self):
        response = self.client.get(f"{self.project_path}/verification/config", headers=self.headers)
        self.assertEqual(response.status_code, 410)
        response = self.client.post(
            f"{self.project_path}/verification/config", headers=self.headers,
        )
        self.assertEqual(response.status_code, 410)

    def test_retired_request_does_not_depend_on_or_read_evidence(self):
        alert_verification_store.configure(
            enabled=True,
            image_egress_authorized=False,
            daily_limit=3,
            model_id="",
            provider_configured=False,
            project_id=self.project_id,
        )
        response = self.client.post(
            f"{self.project_path}/alerts/evt-review/verification",
            headers=self.headers,
            json={},
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"]["code"], "verification_retired")


if __name__ == "__main__":
    unittest.main()
