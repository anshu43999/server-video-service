import asyncio
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.auth as auth_module
import app.main as main_module
from app.config import settings
from app.database import DatabaseManager
from app.project_auth import reset_memory_project_authorization_for_tests
from app.project_management import reset_memory_project_management_for_tests
from app.stream_config import StreamConfigStore


class ProjectStreamIsolationTests(unittest.TestCase):
    def setUp(self):
        main_module.streams.clear()
        main_module.stream_restore_errors.clear()
        self.isolation = ExitStack()
        self.addCleanup(self.isolation.close)
        self.isolation.enter_context(patch("app.main.stream_config_store", StreamConfigStore(None)))
        self.isolation.enter_context(patch("app.auth.database", DatabaseManager(None)))
        self.isolation.enter_context(patch.dict(auth_module._memory_accounts, {}, clear=True))
        self.isolation.enter_context(patch.dict(auth_module._memory_sessions, {}, clear=True))
        self.isolation.enter_context(patch.object(main_module.database, "verify_schema", return_value={"status": "ok"}))
        self.isolation.enter_context(patch.object(main_module.conversion_service, "start"))
        self.isolation.enter_context(patch.object(main_module.conversion_service, "close"))
        self.isolation.enter_context(
            patch.object(main_module.model_catalog, "_load", return_value={"models": [], "activeServerModel": None})
        )
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()
        self.old_settings = {
            "deployment_env": settings.deployment_env,
            "admin_token": settings.admin_token,
            "mobile_token": settings.mobile_token,
        }
        settings.deployment_env = "production"
        settings.admin_token = None
        settings.mobile_token = None
        self.client = TestClient(main_module.app)
        self.client.__enter__()
        setup = self.client.post(
            "/aiyoloapi/auth/setup",
            json={"username": "platform-admin", "password": "platform-admin-password"},
        )
        self.assertEqual(200, setup.status_code, setup.text)
        self.admin = {"Authorization": f"Bearer {setup.json()['accessToken']}"}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for stream in list(main_module.streams.values()):
            asyncio.run(stream.close())
        main_module.streams.clear()
        main_module.stream_restore_errors.clear()
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()
        for name, value in self.old_settings.items():
            setattr(settings, name, value)

    def create_account(self, username: str) -> dict:
        response = self.client.post(
            "/aiyoloapi/platform/accounts",
            headers=self.admin,
            json={
                "username": username,
                "password": f"{username}-password",
                "platformRole": "NORMAL_USER",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def login(self, username: str) -> dict[str, str]:
        response = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": username, "password": f"{username}-password"},
        )
        self.assertEqual(200, response.status_code, response.text)
        return {"Authorization": f"Bearer {response.json()['accessToken']}"}

    def create_project(self, code: str, owner_id: str) -> dict:
        response = self.client.post(
            "/aiyoloapi/projects",
            headers=self.admin,
            json={"projectCode": code, "displayName": code.title(), "ownerAccountId": owner_id},
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def add_user(self, project_id: str, account_id: str) -> None:
        response = self.client.post(
            f"/aiyoloapi/projects/{project_id}/members",
            headers=self.admin,
            json={"accountId": account_id, "projectRole": "PROJECT_USER"},
        )
        self.assertEqual(201, response.status_code, response.text)

    def assert_ws_close(self, url: str, headers: dict[str, str], code: int) -> None:
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect(url, headers=headers):
                pass
        self.assertEqual(code, caught.exception.code)

    def test_two_projects_roles_media_and_websockets_are_isolated(self):
        owner_a = self.create_account("owner-a")
        owner_b = self.create_account("owner-b")
        user_a = self.create_account("user-a")
        user_b = self.create_account("user-b")
        outsider = self.create_account("outsider")
        project_a = self.create_project("project-alpha", owner_a["accountId"])
        project_b = self.create_project("project-beta", owner_b["accountId"])
        project_a_id = project_a["projectId"]
        project_b_id = project_b["projectId"]
        self.add_user(project_a_id, user_a["accountId"])
        self.add_user(project_b_id, user_b["accountId"])
        owner_a_headers = self.login("owner-a")
        owner_b_headers = self.login("owner-b")
        user_a_headers = self.login("user-a")
        user_b_headers = self.login("user-b")
        outsider_headers = self.login("outsider")

        for project_id, headers, host in (
            (project_a_id, owner_a_headers, "camera-a.internal"),
            (project_b_id, owner_b_headers, "camera-b.internal"),
        ):
            response = self.client.post(
                f"/aiyoloapi/projects/{project_id}/streams",
                headers=headers,
                json={
                    "stream_id": "shared-camera",
                    "display_name": "Shared Camera",
                    "source_url": f"rtsp://operator:secret@{host}/live?token=hidden",
                    "enabled": False,
                },
            )
            self.assertEqual(201, response.status_code, response.text)
            self.assertEqual(project_id, response.json()["project_id"])
            self.assertNotIn("secret", response.text)
            self.assertNotIn("token=hidden", response.text)

        key_a = (project_a_id, "shared-camera")
        key_b = (project_b_id, "shared-camera")
        self.assertIsNot(main_module.streams[key_a], main_module.streams[key_b])
        self.assertFalse(hasattr(main_module.streams[key_a], "publisher"))
        self.assertFalse(hasattr(main_module.streams[key_b], "publisher"))
        main_module.streams[key_a].latest_frame = b"project-a-frame"
        main_module.streams[key_b].latest_frame = b"project-b-frame"
        self.assertEqual(b"project-a-frame", main_module.streams[key_a].latest_frame)
        self.assertEqual(b"project-b-frame", main_module.streams[key_b].latest_frame)
        self.assertEqual(2, len(main_module.stream_config_store.list_all()))

        list_a = self.client.get(
            f"/aiyoloapi/projects/{project_a_id}/streams", headers=user_a_headers
        )
        self.assertEqual(200, list_a.status_code, list_a.text)
        self.assertEqual([project_a_id], [item["project_id"] for item in list_a.json()])
        self.assertIn("camera-a.internal", list_a.text)
        self.assertNotIn("camera-b.internal", list_a.text)
        self.assertNotIn("operator", list_a.text)

        playback = self.client.get(
            f"/aiyoloapi/projects/{project_a_id}/streams/shared-camera/playback",
            headers=user_a_headers,
        )
        self.assertEqual(410, playback.status_code, playback.text)
        self.assertNotIn("url", playback.text)
        self.assertNotIn(project_b_id, playback.text)

        sources = self.client.get(
            f"/aiyoloapi/projects/{project_a_id}/capabilities/sources", headers=user_a_headers
        )
        self.assertEqual(200, sources.status_code, sources.text)
        self.assertEqual(1, len(sources.json()["sources"]))
        self.assertEqual(project_a_id, sources.json()["sources"][0]["projectId"])
        self.assertEqual("shared-camera", sources.json()["sources"][0]["sourceId"])

        self.assertEqual(
            400, self.client.get("/aiyoloapi/streams", headers=owner_a_headers).status_code
        )
        compatible = self.client.get(
            "/aiyoloapi/streams",
            headers={**owner_a_headers, "X-Project-Id": project_a_id},
        )
        self.assertEqual(200, compatible.status_code, compatible.text)
        self.assertEqual(project_a_id, compatible.json()[0]["project_id"])

        create_denied = self.client.post(
            f"/aiyoloapi/projects/{project_a_id}/streams",
            headers=user_a_headers,
            json={"stream_id": "forbidden", "enabled": False},
        )
        self.assertEqual(403, create_denied.status_code)
        self.assertEqual(
            403,
            self.client.post(
                f"/aiyoloapi/projects/{project_a_id}/streams/shared-camera/yolo",
                headers=user_a_headers,
                json={"enabled": True},
            ).status_code,
        )
        self.assertEqual(
            403,
            self.client.patch(
                f"/aiyoloapi/projects/{project_a_id}/streams/shared-camera/config",
                headers=user_a_headers,
                json={"confidence": 0.5},
            ).status_code,
        )
        self.assertEqual(
            403,
            self.client.put(
                f"/aiyoloapi/projects/{project_a_id}/streams/shared-camera/model",
                headers=user_a_headers,
                json={"model_id": "any-model"},
            ).status_code,
        )
        self.assertEqual(
            403,
            self.client.delete(
                f"/aiyoloapi/projects/{project_a_id}/streams/shared-camera",
                headers=user_a_headers,
            ).status_code,
        )

        for headers in (owner_a_headers, outsider_headers):
            self.assertEqual(
                404,
                self.client.get(
                    f"/aiyoloapi/projects/{project_b_id}/streams", headers=headers
                ).status_code,
            )
        self.assertEqual(
            404,
            self.client.delete(
                f"/aiyoloapi/projects/{project_b_id}/streams/shared-camera",
                headers=owner_a_headers,
            ).status_code,
        )

        own_detection_url = (
            f"/aiyoloapi/projects/{project_a_id}/streams/shared-camera/detections"
        )
        self.assert_ws_close(own_detection_url, user_a_headers, 1008)
        self.assert_ws_close(
            f"/aiyoloapi/projects/{project_b_id}/streams/shared-camera/detections",
            user_a_headers,
            1008,
        )
        self.assert_ws_close(
            f"/aiyoloapi/projects/{project_b_id}/streams/shared-camera/ws",
            user_a_headers,
            1008,
        )
        self.assert_ws_close(
            f"/aiyoloapi/projects/{project_b_id}/streams/shared-camera/ingest",
            user_a_headers,
            4404,
        )
        with self.client.websocket_connect(
            f"/aiyoloapi/projects/{project_a_id}/streams/shared-camera/ingest",
            headers=user_a_headers,
        ) as websocket:
            websocket.send_text("ping")
            self.assertEqual({"ok": True}, json.loads(websocket.receive_text()))

        asyncio.run(main_module.streams[key_a].close())
        mjpeg = self.client.get(
            f"/aiyoloapi/projects/{project_a_id}/streams/shared-camera/mjpeg",
            headers=user_a_headers,
        )
        self.assertEqual(410, mjpeg.status_code, mjpeg.text)

        disabled = self.client.patch(
            f"/aiyoloapi/projects/{project_a_id}/members/{user_a['accountId']}",
            headers=owner_a_headers,
            json={"expectedRevision": 1, "enabled": False},
        )
        self.assertEqual(200, disabled.status_code, disabled.text)
        self.assertEqual(
            404,
            self.client.get(
                f"/aiyoloapi/projects/{project_a_id}/streams", headers=user_a_headers
            ).status_code,
        )

        suspended = self.client.post(
            f"/aiyoloapi/projects/{project_a_id}/suspend",
            headers=self.admin,
            json={"expectedRevision": 1},
        )
        self.assertEqual(200, suspended.status_code, suspended.text)
        self.assertEqual(
            403,
            self.client.patch(
                f"/aiyoloapi/projects/{project_a_id}/streams/shared-camera/config",
                headers=owner_a_headers,
                json={"confidence": 0.6},
            ).status_code,
        )

        archived = self.client.post(
            f"/aiyoloapi/projects/{project_b_id}/archive",
            headers=self.admin,
            json={"expectedRevision": 1},
        )
        self.assertEqual(200, archived.status_code, archived.text)
        self.assertEqual(
            404,
            self.client.get(
                f"/aiyoloapi/projects/{project_b_id}/streams", headers=user_b_headers
            ).status_code,
        )


if __name__ == "__main__":
    unittest.main()
