import unittest
import time
from contextlib import ExitStack
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

import app.auth as auth_module
import app.main as main_module
from app.config import settings
from app.database import DatabaseManager
from app.main import app, streams
from app.project_auth import reset_memory_project_authorization_for_tests
from app.project_management import reset_memory_project_management_for_tests
from app.stream_config import StreamConfigStore


def frame_jpeg(value: int) -> bytes:
    frame = np.full((48, 64, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    return encoded.tobytes()


class EndToEndTests(unittest.TestCase):
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
        self.old_environment = settings.deployment_env
        self.old_admin = settings.admin_token
        self.old_mobile = settings.mobile_token
        settings.deployment_env = 'production'
        settings.admin_token = None
        settings.mobile_token = None
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()

    def tearDown(self):
        settings.deployment_env = self.old_environment
        settings.admin_token = self.old_admin
        settings.mobile_token = self.old_mobile
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()

    def setup_project(self, client: TestClient) -> tuple[str, dict[str, str]]:
        setup = client.post('/aiyoloapi/auth/setup', json={
            'username': 'e2e-admin', 'password': 'temporary-test-password',
        })
        self.assertEqual(setup.status_code, 200)
        headers = {'Authorization': f"Bearer {setup.json()['accessToken']}"}
        account_id = client.get('/aiyoloapi/auth/me', headers=headers).json()['accountId']
        project = client.post('/aiyoloapi/projects', headers=headers, json={
            'projectCode': 'e2e-project',
            'displayName': 'E2E Project',
            'ownerAccountId': account_id,
        })
        self.assertEqual(project.status_code, 201, project.text)
        return project.json()['projectId'], headers

    def test_multiple_real_frames_round_trip_and_state(self):
        with TestClient(app) as client:
            project_id, headers = self.setup_project(client)
            streams_path = f"/aiyoloapi/projects/{project_id}/streams"
            self.assertEqual(
                client.post(streams_path, headers=headers, json={"stream_id": "e2e"}).status_code,
                201,
            )
            with client.websocket_connect(f"{streams_path}/e2e/ingest", headers=headers) as ingest:
                with client.websocket_connect(f"{streams_path}/e2e/ws", headers=headers) as output:
                    for value in (10, 80, 160, 240):
                        ingest.send_bytes(frame_jpeg(value))
                        received = output.receive_bytes()
                        self.assertTrue(received.startswith(b"\xff\xd8"))
                        time.sleep(0.06)
            details = client.get(streams_path, headers=headers).json()[0]
            self.assertEqual(details["project_id"], project_id)
            self.assertEqual(details["frames_received"], 4)
            self.assertEqual(details["state"], "outputting")


if __name__ == "__main__":
    unittest.main()
