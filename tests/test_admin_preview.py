"""M34-T03: protected PC preview without resurrecting mobile distribution."""
import asyncio
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

import app.auth as auth
import app.main as main
from app.config import settings
from app.detection import Detection, InferenceResult, NormalizedBox
from app.stream import StreamSession
from app.stream_config import StreamConfigStore
from app.project_auth import set_memory_project, remove_memory_membership
from project_api_support import ProjectApiSupport


class AdminPreviewPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stream = StreamSession("camera", project_id="project-a", alert_runtime=Mock())
        self.frame = np.zeros((100, 160, 3), dtype=np.uint8)
        self.addAsyncCleanup(self.stream.close)

    async def submit(self):
        await self.stream.ingest_frame(self.frame, enforce_rate_limit=False)
        if self.stream._processing_task:
            await self.stream._processing_task

    async def enable_model(self):
        self.stream.detector._load = Mock()
        self.stream.detector.infer = Mock(return_value=InferenceResult(
            frame_width=160, frame_height=100, provides=("BOX",),
            detections=(Detection(0, "person", .9, NormalizedBox(.1, .1, .5, .6)),)))
        await self.stream.set_yolo(True)

    async def test_raw_preview_without_yolo_or_publisher(self):
        with patch("subprocess.Popen", side_effect=AssertionError("publisher process")):
            await self.submit()
            image, mode = await self.stream.admin_preview()
            self.assertEqual("raw", mode)
            self.assertEqual((100, 160, 3), cv2.imdecode(np.frombuffer(image, np.uint8), 1).shape)
            self.assertIsNone(self.stream.latest_jpeg)
            self.assertFalse(self.stream.try_subscribe())
            self.assertIsNone(await self.stream.wait_frame())
            self.stream.alert_runtime.process.assert_not_called()

    async def test_yolo_overlay_and_alert_do_not_depend_on_preview(self):
        await self.enable_model()
        with patch("app.stream.cv2.imencode", wraps=cv2.imencode) as encode:
            await self.submit()
            encode.assert_not_called()
            self.stream.alert_runtime.process.assert_called_once()
            image, mode = await self.stream.admin_preview()
            self.assertEqual("yolo", mode)
            self.assertGreater(cv2.imdecode(np.frombuffer(image, np.uint8), 1).sum(), 0)
            await self.stream.admin_preview()
            self.assertEqual(1, encode.call_count)
            self.stream.alert_runtime.process.assert_called_once()

    async def test_disable_overlay_disable_yolo_and_revocation_clear_annotation(self):
        await self.enable_model()
        await self.submit()
        self.assertEqual("yolo", (await self.stream.admin_preview())[1])
        self.stream.overlay_enabled = False
        self.assertEqual("raw", (await self.stream.admin_preview())[1])
        self.stream.overlay_enabled = True
        self.stream.model_authorizer = lambda: False
        image, mode = await self.stream.admin_preview()
        self.assertEqual("raw", mode)
        self.assertEqual(0, cv2.imdecode(np.frombuffer(image, np.uint8), 1).sum())
        await self.stream.set_yolo(False)
        self.assertEqual("raw", (await self.stream.admin_preview())[1])

    async def test_missing_model_keeps_raw_preview_and_does_not_alert(self):
        await self.enable_model()
        self.stream.detector._load_error = "unavailable"
        await self.submit()
        self.assertEqual("raw", (await self.stream.admin_preview())[1])
        self.stream.alert_runtime.process.assert_not_called()

    async def test_rebind_discards_previous_model_overlay(self):
        await self.enable_model()
        await self.submit()
        self.stream.bind_model(model_id="new", model_path="not-loaded.pt")
        self.assertEqual("raw", (await self.stream.admin_preview())[1])

    async def test_waiting_stale_and_closed_never_return_a_frozen_frame(self):
        self.assertIsNone(await self.stream.admin_preview())
        await self.submit()
        self.assertIsNotNone(await self.stream.admin_preview())
        self.stream._last_frame_received_at = time.monotonic() - 4
        self.assertIsNone(await self.stream.admin_preview())
        await self.submit()
        await self.stream.close()
        self.assertIsNone(await self.stream.admin_preview())
        self.assertIsNone(self.stream._preview_frame)
        self.assertIsNone(self.stream._preview_result)

    async def test_preview_encoding_is_bounded_and_shared_between_viewers(self):
        self.frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        await self.submit()
        with patch("app.stream.cv2.imencode", wraps=cv2.imencode) as encode:
            values = await asyncio.gather(*(self.stream.admin_preview() for _ in range(8)))
            self.assertEqual(1, encode.call_count)
        self.assertEqual((720, 1280, 3), cv2.imdecode(np.frombuffer(values[0][0], np.uint8), 1).shape)

    async def test_close_during_encoding_discards_inflight_frame(self):
        await self.submit()
        real_encode = cv2.imencode
        def close_during_encode(*args):
            self.stream._closed = True
            return real_encode(*args)
        with patch("app.stream.cv2.imencode", side_effect=close_during_encode):
            self.assertIsNone(await self.stream.admin_preview())


class AdminPreviewApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.store = patch("app.main.stream_config_store", StreamConfigStore(None))
        self.store.start()
        self.addCleanup(self.store.stop)
        self.registry = patch.dict(main.streams, {}, clear=True)
        self.registry.start()
        self.addCleanup(self.registry.stop)
        self.start_project_api("preview")
        self.stream = StreamSession("camera", project_id=self.project_id)
        main.streams[(self.project_id, "camera")] = self.stream
        self.url = self.project_path + "/streams/camera/preview"
        self.client.portal.call(self.stream.ingest_frame, np.zeros((32, 48, 3), np.uint8))

    def test_pc_cookie_returns_real_jpeg_without_playback_addresses(self):
        response = self.client.get(self.url)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("image/jpeg", response.headers["content-type"])
        self.assertEqual("raw", response.headers["x-preview-mode"])
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual("same-origin", response.headers["cross-origin-resource-policy"])
        self.assertTrue(response.content.startswith(b"\xff\xd8"))

    def test_bearer_mobile_or_service_channel_cannot_use_preview(self):
        # Even with a valid PC cookie present, the bearer request cannot use it.
        response = self.client.get(self.url, headers=self.headers)
        self.assertEqual(403, response.status_code)
        self.assertEqual("admin_preview_session_required", response.json()["detail"]["code"])
        self.client.cookies.clear()
        self.assertEqual(403, self.client.get(self.url).status_code)

    def test_cross_origin_and_invalid_cookie_are_denied(self):
        self.assertEqual(403, self.client.get(self.url, headers={"Sec-Fetch-Site": "cross-site"}).status_code)
        self.client.cookies.clear()
        self.client.cookies.set(auth.SESSION_COOKIE, "invalid")
        self.assertEqual(401, self.client.get(self.url).status_code)

    def test_no_frame_or_stale_source_has_no_cacheable_image(self):
        self.stream._last_frame_received_at = time.monotonic() - 4
        response = self.client.get(self.url)
        self.assertEqual(204, response.status_code)
        self.assertEqual(b"", response.content)
        self.assertIn("no-store", response.headers["cache-control"])

    def test_explicit_project_and_retired_routes_remain_required(self):
        self.assertEqual(404, self.client.get("/aiyoloapi/streams/camera/preview").status_code)
        for suffix in ("mjpeg", "playback"):
            self.assertEqual(410, self.client.get(self.project_path + "/streams/camera/" + suffix).status_code)
        self.assertEqual(404, self.client.get(self.project_path + "/streams/foreign/preview").status_code)

    def normal_member(self):
        response = self.client.post("/aiyoloapi/platform/accounts", headers=self.headers, json={
            "username": "preview-user", "password": "preview-user-password", "platformRole": "NORMAL_USER"})
        self.assertEqual(201, response.status_code, response.text)
        account_id = response.json()["accountId"]
        membership = self.client.post(self.project_path + "/members", headers=self.headers,
            json={"accountId": account_id, "projectRole": "PROJECT_USER"})
        self.assertEqual(201, membership.status_code, membership.text)
        login = self.client.post("/aiyoloapi/auth/login", json={"username": "preview-user", "password": "preview-user-password"})
        self.assertEqual(200, login.status_code)
        return account_id

    def test_project_user_can_view_but_cannot_view_another_project(self):
        other = self.client.post("/aiyoloapi/projects", headers=self.headers,
            json={"projectCode": "other", "displayName": "Other", "ownerAccountId": self.account_id}).json()["projectId"]
        other_stream = StreamSession("camera", project_id=other)
        main.streams[(other, "camera")] = other_stream
        self.client.portal.call(other_stream.ingest_frame, np.full((32, 48, 3), 255, np.uint8))
        self.normal_member()
        self.assertEqual(200, self.client.get(self.url).status_code)
        response = self.client.get(f"/aiyoloapi/projects/{other}/streams/camera/preview")
        self.assertEqual(404, response.status_code)
        self.assertNotIn("image/jpeg", response.headers["content-type"])

    def test_logout_during_encoding_prevents_response(self):
        original = self.stream.admin_preview
        token = self.client.cookies.get(auth.SESSION_COOKIE)
        async def revoked():
            result = await original()
            auth.revoke_session(token)
            return result
        with patch.object(self.stream, "admin_preview", side_effect=revoked):
            self.assertEqual(401, self.client.get(self.url).status_code)

    def test_membership_revocation_takes_effect_on_next_frame(self):
        account_id = self.normal_member()
        self.assertEqual(200, self.client.get(self.url).status_code)
        response = self.client.delete(self.project_path + f"/members/{account_id}?expectedRevision=1", headers=self.headers)
        self.assertIn(response.status_code, (200, 204), response.text)
        self.assertEqual(404, self.client.get(self.url).status_code)

    def test_deleted_session_during_encoding_prevents_response(self):
        original = self.stream.admin_preview
        async def removed():
            result = await original()
            main.streams.pop((self.project_id, "camera"))
            return result
        with patch.object(self.stream, "admin_preview", side_effect=removed):
            self.assertEqual(404, self.client.get(self.url).status_code)

    def test_suspended_and_archived_projects_cannot_preview(self):
        for state in ("SUSPENDED", "ARCHIVED"):
            with self.subTest(state=state):
                set_memory_project(self.project_id, "preview", lifecycle_state=state, revision=2)
                self.assertEqual(403, self.client.get(self.url).status_code)

    def test_membership_revoked_during_encoding_cannot_deliver_a_last_frame(self):
        account_id = self.normal_member()
        original = self.stream.admin_preview
        async def revoked():
            result = await original()
            remove_memory_membership(self.project_id, account_id)
            return result
        with patch.object(self.stream, "admin_preview", side_effect=revoked):
            self.assertEqual(404, self.client.get(self.url).status_code)
