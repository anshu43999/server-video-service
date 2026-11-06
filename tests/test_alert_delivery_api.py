import unittest

from fastapi.testclient import TestClient

from app.main import alert_delivery, app, settings
from project_api_support import ProjectApiSupport


class AlertDeliveryApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        alert_delivery.last_receipts.clear()
        self.start_project_api("delivery-project")

    def tearDown(self):
        self.stop_project_api()

    def test_test_delivery_is_accepted_and_requires_admin(self):
        with TestClient(app) as anonymous:
            denied = anonymous.post(
                f"{self.project_path}/alerts/test-delivery",
                json={"event": {"eventId": "evt"}},
            )
        self.assertEqual(denied.status_code, 401)
        response = self.client.post(
            f"{self.project_path}/alerts/test-delivery",
            headers=self.headers,
            json={"event": {"eventId": "evt"}, "channels": ["management", "email", "sms", "enterprise_im"]},
        )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["accepted"])
        self.assertEqual(len(response.json()["deliveryIds"]), 4)

    def test_status_does_not_expose_credentials_or_allow_webhook(self):
        response = self.client.get(
            f"{self.project_path}/alerts/delivery/status", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("credential", response.text.lower())
        invalid = self.client.post(
            f"{self.project_path}/alerts/test-delivery",
            headers=self.headers,
            json={"event": {"eventId": "evt"}, "channels": ["webhook"]},
        )
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
