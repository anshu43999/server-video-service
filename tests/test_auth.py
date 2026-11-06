import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
import app.main as main_module
from app.main import app, streams
from app.stream import StreamSession


class AuthTests(unittest.TestCase):
    def setUp(self):
        streams.clear()
        self.original_environment = settings.deployment_env
        self.original_admin = settings.admin_token
        self.original_mobile = settings.mobile_token
        settings.deployment_env = "development"
        self.start_patch = patch.object(main_module.conversion_service, "start")
        self.close_patch = patch.object(main_module.conversion_service, "close")
        self.start_patch.start()
        self.close_patch.start()

    def tearDown(self):
        settings.deployment_env = self.original_environment
        settings.admin_token = self.original_admin
        settings.mobile_token = self.original_mobile
        self.start_patch.stop()
        self.close_patch.stop()

    def test_legacy_admin_token_cannot_mutate_project_streams(self):
        settings.admin_token = "admin-secret"
        stream_id = f"secure-{uuid4().hex}"
        headers = {
            "X-Admin-Token": "admin-secret",
            "X-Project-Id": "00000000-0000-0000-0000-000000000001",
        }
        with TestClient(app) as client:
            self.assertEqual(client.post("/aiyoloapi/streams", json={"stream_id": stream_id}).status_code, 401)
            response = client.post(
                "/aiyoloapi/streams",
                json={"stream_id": stream_id},
                headers=headers,
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(client.patch(f"/aiyoloapi/streams/{stream_id}/config", json={"max_fps": 12}).status_code, 401)
            self.assertEqual(
                client.patch(
                    f"/aiyoloapi/streams/{stream_id}/config",
                    json={"max_fps": 12},
                    headers=headers,
                ).status_code,
                401,
            )

    def test_legacy_mobile_token_cannot_enter_project_ingest(self):
        settings.mobile_token = "mobile-secret"
        with TestClient(app) as client:
            streams["secure"] = StreamSession("secure")
            for headers in (
                {},
                {
                    "X-Video-Service-Token": "mobile-secret",
                    "X-Project-Id": "00000000-0000-0000-0000-000000000001",
                },
            ):
                with self.assertRaises(WebSocketDisconnect) as caught:
                    with client.websocket_connect(
                        "/aiyoloapi/streams/secure/ingest", headers=headers
                    ):
                        pass
                self.assertEqual(caught.exception.code, 4401)

    def test_production_rejects_static_admin_and_mobile_tokens(self):
        settings.deployment_env = "production"
        settings.admin_token = "admin-secret"
        settings.mobile_token = "mobile-secret"
        with TestClient(app) as client:
            self.assertEqual(
                client.post(
                    "/aiyoloapi/streams",
                    json={"stream_id": "secure"},
                    headers={"X-Admin-Token": "admin-secret"},
                ).status_code,
                401,
            )
            streams["secure"] = StreamSession("secure")
            with self.assertRaises(WebSocketDisconnect) as caught:
                with client.websocket_connect(
                    "/aiyoloapi/streams/secure/ingest",
                    headers={
                        "X-Video-Service-Token": "mobile-secret",
                        "X-Project-Id": "00000000-0000-0000-0000-000000000001",
                    },
                ):
                    pass
            self.assertEqual(caught.exception.code, 4401)


if __name__ == "__main__":
    unittest.main()
