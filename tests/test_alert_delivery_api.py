import unittest

from fastapi.testclient import TestClient

from app.main import alert_delivery, app, settings


class AlertDeliveryApiTests(unittest.TestCase):
    def setUp(self):
        self.old_admin, self.old_mobile = settings.admin_token, settings.mobile_token
        settings.admin_token, settings.mobile_token = "admin-secret", "mobile-secret"
        alert_delivery.last_receipts.clear()
        self.client = TestClient(app)

    def tearDown(self):
        settings.admin_token, settings.mobile_token = self.old_admin, self.old_mobile

    def test_test_delivery_is_accepted_and_requires_admin(self):
        denied = self.client.post("/api/alerts/test-delivery", json={"event": {"eventId": "evt"}})
        self.assertEqual(denied.status_code, 401)
        response = self.client.post(
            "/api/alerts/test-delivery",
            headers={"X-Admin-Token": "admin-secret"},
            json={"event": {"eventId": "evt"}, "channels": ["management", "email", "sms", "enterprise_im"]},
        )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["accepted"])
        self.assertEqual(len(response.json()["deliveryIds"]), 4)

    def test_status_does_not_expose_credentials_or_allow_webhook(self):
        response = self.client.get("/api/alerts/delivery/status", headers={"X-Admin-Token": "admin-secret"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("credential", response.text.lower())
        invalid = self.client.post(
            "/api/alerts/test-delivery",
            headers={"X-Admin-Token": "admin-secret"},
            json={"event": {"eventId": "evt"}, "channels": ["webhook"]},
        )
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
