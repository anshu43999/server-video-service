import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, settings
from app.alerts.disposition import alert_disposition_store
from project_api_support import ProjectApiSupport


class AlertDispositionApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.old_database = alert_disposition_store.database_manager
        alert_disposition_store.configure_database(None)
        alert_disposition_store.reset()
        self.start_project_api("disposition-project")
        account = self.client.post(
            "/aiyoloapi/platform/accounts",
            headers=self.headers,
            json={
                "username": "disposition-user",
                "password": "temporary-test-password",
                "platformRole": "NORMAL_USER",
            },
        ).json()
        self.client.post(
            f"{self.project_path}/members",
            headers=self.headers,
            json={"accountId": account["accountId"], "projectRole": "PROJECT_USER"},
        )
        login = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": "disposition-user", "password": "temporary-test-password"},
        ).json()
        self.user_headers = {"Authorization": f"Bearer {login['accessToken']}"}
        self.user_account_id = account["accountId"]
        alert_disposition_store.register({
            "eventId": "evt-api", "ruleId": "r1", "sourceId": "cam", "subjectKey": "track:1",
            "confirmedAtUs": 100, "effectiveThresholds": {"minConfidence": .8},
            "evidence": {"snapshotUri": "/srv/evidence/frame.jpg"},
            "detectionResults": [{"label": "x"}], "disposition": {"status": "OPEN"},
        }, project_id=self.project_id)

    def tearDown(self):
        alert_disposition_store.reset()
        alert_disposition_store.configure_database(self.old_database)
        self.stop_project_api()

    def test_project_user_can_read_and_dispose(self):
        response = self.client.get(
            f"{self.project_path}/alerts", headers=self.user_headers
        )
        self.assertEqual(response.status_code, 200)
        disposed = self.client.post(
            f"{self.project_path}/alerts/evt-api/acknowledge",
            headers={**self.user_headers, "X-Actor": "forged"},
            json={},
        )
        self.assertEqual(disposed.status_code, 200)
        self.assertEqual(self.user_account_id, disposed.json()["disposition"]["actor"])

    def test_admin_disposition_and_safe_export(self):
        response = self.client.post(
            f"{self.project_path}/alerts/evt-api/false-positive",
            headers={**self.headers, "X-Operator-Id": "forged-reviewer"},
            json={"actedAtUs": 200, "screenshot": "C:\\private\\frame.jpg"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["disposition"]["status"], "FALSE_POSITIVE")
        self.assertEqual(self.account_id, response.json()["disposition"]["actor"])
        self.assertEqual(
            403,
            self.client.get(
                f"{self.project_path}/alerts/false-positives/export",
                headers=self.user_headers,
            ).status_code,
        )
        exported = self.client.get(
            f"{self.project_path}/alerts/false-positives/export", headers=self.headers
        )
        self.assertEqual(exported.status_code, 200)
        self.assertNotIn("C:\\private", exported.text)
        self.assertIn("evidence/frame.jpg", exported.text)

    def test_false_positive_feedback_never_persists_or_exports_inline_data_url(self):
        data_url = "data:image/png;base64,c2VjcmV0LWltYWdlLWJ5dGVz"
        alert_disposition_store.register({
            "eventId": "evt-inline-feedback", "ruleId": "r1", "sourceId": "cam",
            "evidence": {"snapshotUri": data_url}, "disposition": {"status": "OPEN"},
        }, project_id=self.project_id)
        response = self.client.post(
            f"{self.project_path}/alerts/evt-inline-feedback/false-positive",
            headers=self.headers, json={"actedAtUs": 201},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("data:image", response.text)
        self.assertNotIn("secret-image-bytes", response.text)
        self.assertIn("/alerts/evt-inline-feedback/evidence", response.text)
        feedback = alert_disposition_store.feedback(self.project_id)
        self.assertEqual(len(feedback), 1)
        self.assertIn(f"/alerts/evt-inline-feedback/evidence", feedback[0]["image"])
        self.assertNotIn("data:image", str(feedback))
        self.assertNotIn("secret-image-bytes", str(feedback))
        exported = self.client.get(
            f"{self.project_path}/alerts/false-positives/export", headers=self.headers,
        )
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertNotIn("data:image", exported.text)
        self.assertNotIn("secret-image-bytes", exported.text)
        # Metadata redaction must not erase the only legacy backing image.
        self.assertEqual(data_url, alert_disposition_store.get(
            "evt-inline-feedback", self.project_id)["evidence"]["snapshotUri"])
        image = self.client.get(
            f"{self.project_path}/alerts/evt-inline-feedback/evidence", headers=self.headers,
        )
        self.assertEqual(image.status_code, 200, image.text)
        self.assertEqual(image.content, b"secret-image-bytes")
        for path in (f"{self.project_path}/alerts", f"{self.project_path}/alerts/evt-inline-feedback"):
            metadata = self.client.get(path, headers=self.headers)
            self.assertEqual(metadata.status_code, 200)
            self.assertNotIn("data:image", metadata.text)

    def test_server_url_feedback_keeps_resolvable_project_authenticated_reference(self):
        event_id = "evt-server-1234567890abcdef12345678"
        alert_disposition_store.register({
            "eventId": event_id, "origin": "SERVER_STREAM",
            "evidence": {"snapshotUri": f"https://legacy.invalid/aiyoloapi/alerts/{event_id}/evidence?token=DO_NOT_EXPORT"},
        }, project_id=self.project_id)
        response = self.client.post(f"{self.project_path}/alerts/{event_id}/false-positive",
                                    headers=self.headers, json={"actedAtUs": 202})
        self.assertEqual(response.status_code, 200)
        exported = self.client.get(f"{self.project_path}/alerts/false-positives/export", headers=self.headers)
        ref = exported.json()["entries"][0]["image"]
        self.assertEqual(ref, f"{self.project_path}/alerts/{event_id}/evidence")
        self.assertNotIn("DO_NOT_EXPORT", exported.text)
        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "server.jpg"
            image_path.write_bytes(b"server-image")
            with patch("app.main.server_alert_runtime.evidence_path", return_value=image_path):
                image = self.client.get(ref, headers=self.headers)
                self.assertEqual(image.status_code, 200)
                self.assertEqual(image.content, b"server-image")
                self.client.cookies.clear()
                self.assertEqual(self.client.get(ref).status_code, 401)
                foreign = ref.replace(self.project_id, "foreign-project")
                self.assertEqual(self.client.get(foreign, headers=self.user_headers).status_code, 404)


if __name__ == "__main__":
    unittest.main()
