"""Real ASGI/SQLite/JPEG boundary; controlled inference, no live video clients."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from starlette.websockets import WebSocketDisconnect

import app.main as main
from app.alerts.delivery import AlertDeliveryService
from app.alerts.disposition import AlertDispositionStore
from app.alerts.runtime import ServerAlertRuntime
from app.database import Base, DatabaseManager
from app.detection import Detection, InferenceResult, NormalizedBox
from app.stream import StreamSession
from app.stream_config import StreamConfigStore
from project_api_support import ProjectApiSupport


class AlertNotificationsClosureApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory(prefix="m34-t05-api-"))
        self.database = DatabaseManager("sqlite+pysqlite:///" + (Path(self.temp) / "alerts.db").as_posix())
        self.addCleanup(self.database.close)
        Base.metadata.create_all(self.database.engine)
        self.events = AlertDispositionStore(self.database)
        self.delivery = AlertDeliveryService(database_manager=self.database, retry_delay_seconds=0)
        self.enterContext(patch("app.main.alert_delivery", self.delivery))
        self.enterContext(patch("app.main.alert_disposition_store", self.events))
        self.enterContext(patch("app.main.stream_config_store", StreamConfigStore(None)))
        self.enterContext(patch.dict(main.streams, {}, clear=True))
        self.start_project_api("closure")
        user = self.client.post("/aiyoloapi/platform/accounts", headers=self.headers, json={
            "username": "closure-user", "password": "temporary-test-password", "platformRole": "NORMAL_USER"
        }).json()
        self.user_id = user["accountId"]
        self.client.post(f"{self.project_path}/members", headers=self.headers,
            json={"accountId": self.user_id, "projectRole": "PROJECT_USER"}).raise_for_status()
        login = self.client.post("/aiyoloapi/auth/login", json={
            "username": "closure-user", "password": "temporary-test-password"}).json()
        self.user_headers = {"Authorization": "Bearer " + login["accessToken"]}
        self.other = self.client.post("/aiyoloapi/projects", headers=self.headers, json={
            "projectCode": "closure-other", "displayName": "Other", "ownerAccountId": self.account_id
        }).json()["projectId"]
        profile = {"modelVersion": "1", "revision": 1, "alertRules": [{"enabled": True,
            "rawLabel": "person", "eventCode": "PERSON", "camera": {"minimumConfidence": .7,
            "minimumConsecutiveFrames": 2, "minimumDwellTimeMs": 0, "cooldownMs": 1000}}]}
        self.runtime = ServerAlertRuntime(model_provider=lambda *args: {"modelId": "fixture", "version": "1"},
            parameter_store=None, event_store=self.events, delivery_service=self.delivery,
            evidence_root=Path(self.temp) / "evidence", profile_provider=lambda *args: profile)
        self.enterContext(patch("app.main.server_alert_runtime", self.runtime))
        self.stream = StreamSession("camera-shared", project_id=self.project_id, alert_runtime=self.runtime)
        self.stream.yolo_enabled = True
        self.stream.detector._load = Mock()
        self.stream.detector.infer = Mock(return_value=InferenceResult(
            model_id="fixture", class_names=("person",), provides=("BOX",),
            detections=(Detection(0, "person", .9, NormalizedBox(.1, .1, .3, .5)),),
            frame_width=48, frame_height=32))
        main.streams[(self.project_id, "camera-shared")] = self.stream

    def tearDown(self):
        if self.client:
            self.client.portal.call(self.stream.close)
            self.client.portal.call(self.delivery.close)
        self.stop_project_api()

    async def produce(self, count=2):
        for _ in range(count):
            await self.stream.ingest_frame(np.zeros((32, 48, 3), dtype=np.uint8), enforce_rate_limit=False)
            await asyncio.wait_for(self.stream._processing_task, 2)
        await self.delivery.drain()

    def alerts(self):
        response = self.client.get(f"{self.project_path}/alerts", headers=self.user_headers)
        self.assertEqual(200, response.status_code)
        return response.json()["events"]

    def test_formal_alert_reaches_both_channels_without_any_video_consumer(self):
        with self.client.websocket_connect(f"{self.project_path}/alerts/ws", headers=self.user_headers) as pc:
            with self.client.websocket_connect(f"{self.project_path}/alerts/notifications", headers=self.user_headers) as mobile:
                self.client.portal.call(self.produce, 1)
                self.assertEqual([], self.alerts())  # A detection alone is not an alert.
                self.client.portal.call(self.produce, 1)
                event = self.alerts()[0]
                for socket in (pc, mobile):
                    message = socket.receive_json()
                    self.assertEqual("alert", message["type"])
                    self.assertEqual(event["eventId"], message["event"]["eventId"])
                    self.assertEqual("camera-shared", message["event"]["streamId"])
                    self.assertNotIn("playback", str(message).lower())
                self.assertEqual(0, self.stream.active_subscribers)
                self.assertIsNone(self.stream.latest_jpeg)
                evidence = self.client.get(f"{self.project_path}/alerts/{event['eventId']}/evidence", headers=self.user_headers)
                self.assertEqual(200, evidence.status_code)
                self.assertTrue(evidence.content.startswith(b"\xff\xd8"))
                preview = self.client.get(f"{self.project_path}/streams/camera-shared/preview")
                self.assertEqual(200, preview.status_code)  # Authorized PC cookie only.
                self.client.portal.call(self.produce, 2)
                self.assertEqual(1, len(self.alerts()))
                for name in ("management", "app"):
                    self.assertEqual(1, len([r for r in self.delivery.last_receipts if r.channel == name]))

    def test_disconnected_consumers_catch_up_from_rest_without_reinserting_event(self):
        self.client.portal.call(self.produce)
        original = self.alerts()[0]
        for _ in range(2):
            with self.client.websocket_connect(f"{self.project_path}/alerts/notifications", headers=self.user_headers):
                self.assertEqual([original["eventId"]], [event["eventId"] for event in self.alerts()])
                self.client.portal.call(self.produce)
        self.assertEqual(1, len(self.events.list(project_id=self.project_id)))
        self.assertEqual(1, len([r for r in self.delivery.last_receipts if r.channel == "app"]))
        self.assertEqual(0, self.delivery.channels["app"].subscriber_count)

    def test_membership_revocation_closes_existing_pc_and_mobile_before_next_event(self):
        with self.client.websocket_connect(f"{self.project_path}/alerts/ws", headers=self.user_headers) as pc:
            with self.client.websocket_connect(f"{self.project_path}/alerts/notifications", headers=self.user_headers) as mobile:
                removed = self.client.delete(f"{self.project_path}/members/{self.user_id}", params={"expectedRevision": 1}, headers=self.headers)
                self.assertEqual(204, removed.status_code)
                self.client.portal.call(self.produce)
                for socket in (pc, mobile):
                    message = socket.receive()
                    self.assertEqual("websocket.close", message["type"])
                    self.assertEqual(4404, message["code"])
        event = self.events.list(project_id=self.project_id)[0]
        self.assertEqual(404, self.client.get(f"{self.project_path}/alerts", headers=self.user_headers).status_code)
        self.assertEqual(404, self.client.get(f"{self.project_path}/alerts/{event['eventId']}/evidence", headers=self.user_headers).status_code)

    def test_idle_subscription_revocation_closes_without_waiting_for_an_alert(self):
        with self.client.websocket_connect(f"{self.project_path}/alerts/notifications", headers=self.user_headers) as mobile:
            self.client.delete(f"{self.project_path}/members/{self.user_id}", params={"expectedRevision": 1}, headers=self.headers).raise_for_status()
            message = mobile.receive()
            self.assertEqual("websocket.close", message["type"])
            self.assertEqual(4404, message["code"])

    def test_other_project_and_retired_video_are_not_notification_destinations(self):
        for suffix in ("ws", "notifications"):
            with self.assertRaises(WebSocketDisconnect) as error:
                with self.client.websocket_connect(f"/aiyoloapi/projects/{self.other}/alerts/{suffix}", headers=self.user_headers):
                    pass
            self.assertEqual(4404, error.exception.code)
        self.assertEqual(403, self.client.get(f"{self.project_path}/streams/camera-shared/preview", headers=self.user_headers).status_code)
        self.assertEqual(410, self.client.get(f"{self.project_path}/streams/camera-shared/playback", headers=self.user_headers).status_code)
        with self.assertRaises(WebSocketDisconnect) as error:
            with self.client.websocket_connect(f"{self.project_path}/streams/camera-shared/detections", headers=self.user_headers):
                pass
        self.assertEqual(1008, error.exception.code)

    def test_project_suspension_closes_queued_notifications_but_preserves_historical_read(self):
        self.client.portal.call(self.produce)
        with self.client.websocket_connect(f"{self.project_path}/alerts/ws", headers=self.user_headers) as pc:
            suspended = self.client.post(f"{self.project_path}/suspend", headers=self.headers,
                json={"expectedRevision": 1})
            self.assertEqual(200, suspended.status_code, suspended.text)
            message = pc.receive()
            self.assertEqual("websocket.close", message["type"])
            self.assertEqual(4403, message["code"])
        self.assertEqual(1, len(self.alerts()))
        with self.assertRaises(WebSocketDisconnect) as error:
            with self.client.websocket_connect(f"{self.project_path}/alerts/notifications", headers=self.user_headers):
                pass
        self.assertEqual(4403, error.exception.code)


if __name__ == "__main__":
    unittest.main()
