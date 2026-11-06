import asyncio
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app, streams
from app.stream_config import StreamConfigStore
from app.database import DatabaseManager
from app.project_auth import reset_memory_project_authorization_for_tests
from app.project_management import reset_memory_project_management_for_tests
import app.auth as auth_module
import app.main as main_module


def make_jpeg() -> bytes:
    image = np.full((24, 32, 3), 128, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


class ApiTests(unittest.TestCase):
    def setUp(self):
        streams.clear()
        self.isolation = ExitStack()
        self.addCleanup(self.isolation.close)
        self.isolation.enter_context(patch('app.main.stream_config_store', StreamConfigStore(None)))
        self.isolation.enter_context(patch('app.auth.database', DatabaseManager(None)))
        self.isolation.enter_context(patch.dict(auth_module._memory_accounts, {}, clear=True))
        self.isolation.enter_context(patch.dict(auth_module._memory_sessions, {}, clear=True))
        self.isolation.enter_context(patch.object(main_module.database, 'verify_schema', return_value={'status': 'ok'}))
        self.isolation.enter_context(patch.object(main_module.conversion_service, 'start'))
        self.isolation.enter_context(patch.object(main_module.conversion_service, 'close'))
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()
        self.addCleanup(reset_memory_project_authorization_for_tests)
        self.addCleanup(reset_memory_project_management_for_tests)

    def login(self, client):
        setup = client.post('/aiyoloapi/auth/setup', json={
            'username': 'api-test-admin', 'password': 'temporary-test-password',
        })
        self.assertEqual(setup.status_code, 200)
        account_id = client.get('/aiyoloapi/auth/me').json()['accountId']
        project = client.post('/aiyoloapi/projects', json={
            'projectCode': 'api-test-project',
            'displayName': 'API Test Project',
            'ownerAccountId': account_id,
        })
        self.assertEqual(project.status_code, 201, project.text)
        return project.json()['projectId']

    def test_create_toggle_and_ingest(self):
        with TestClient(app) as client:
            project_id = self.login(client)
            admin = client.get("/")
            self.assertEqual(admin.status_code, 200)
            self.assertEqual(client.get("/", follow_redirects=False).headers["location"], "/admin/")
            self.assertIn('id="app"', admin.text)
            self.assertIn('/admin/assets/', admin.text)
            self.assertEqual(client.get("/admin/styles.css").status_code, 404)
            self.assertEqual(client.get("/admin/app.js").status_code, 404)
            stream_path = f"/aiyoloapi/projects/{project_id}/streams"
            response = client.post(stream_path, json={"stream_id": "demo"})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["state"], "created")
            response = client.patch(f"{stream_path}/demo/config", json={"confidence": 0.4, "max_fps": 12})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["confidence"], 0.4)
            self.assertEqual(response.json()["max_fps"], 12.0)
            self.assertTrue(response.json()["overlay_enabled"])
            response = client.patch(f"{stream_path}/demo/config", json={"overlay_enabled": False})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["overlay_enabled"])
            self.assertFalse(streams[(project_id, "demo")].overlay_enabled)
            response = client.patch(f"{stream_path}/demo/config", json={"overlay_enabled": True})
            self.assertTrue(response.json()["overlay_enabled"])
            with client.websocket_connect(f"{stream_path}/demo/ingest") as ws:
                ws.send_bytes(make_jpeg())
            self.assertEqual(streams[(project_id, "demo")].frames_received, 1)
            response = client.get(stream_path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()[0]["stream_id"], "demo")
            self.assertEqual(response.json()[0]["state"], "outputting")
            self.assertIn("model", response.json()[0])
            self.assertIn("frames_fallback", response.json()[0])

    def test_stream_id_uses_frozen_safe_charset(self):
        with TestClient(app) as client:
            project_id = self.login(client)
            response = client.post(
                f"/aiyoloapi/projects/{project_id}/streams", json={"stream_id": "bad/id"}
            )
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
