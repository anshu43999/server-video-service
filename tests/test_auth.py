import unittest

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, streams
from app.stream import StreamSession


class AuthTests(unittest.TestCase):
    def setUp(self):
        streams.clear()
        self.original_admin = settings.admin_token
        self.original_mobile = settings.mobile_token

    def tearDown(self):
        settings.admin_token = self.original_admin
        settings.mobile_token = self.original_mobile

    def test_admin_mutations_require_admin_token_when_configured(self):
        settings.admin_token = "admin-secret"
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/streams", json={"stream_id": "secure"}).status_code, 401)
            response = client.post(
                "/api/streams",
                json={"stream_id": "secure"},
                headers={"X-Admin-Token": "admin-secret"},
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(client.patch("/api/streams/secure/config", json={"max_fps": 12}).status_code, 401)
            self.assertEqual(client.patch("/api/streams/secure/config", json={"max_fps": 12}, headers={"X-Admin-Token": "admin-secret"}).status_code, 200)

    def test_ingest_requires_mobile_token_when_configured(self):
        settings.mobile_token = "mobile-secret"
        with TestClient(app) as client:
            streams["secure"] = StreamSession("secure")
            with client.websocket_connect("/api/streams/secure/ingest") as websocket:
                message = websocket.receive()
                self.assertEqual(message["type"], "websocket.close")
                self.assertEqual(message["code"], 4401)
            with client.websocket_connect("/api/streams/secure/ingest", headers={"X-Video-Service-Token": "mobile-secret"}):
                pass


if __name__ == "__main__":
    unittest.main()
