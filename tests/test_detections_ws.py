import asyncio
import json
import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.detection import Detection, FrameDetections, InferenceResult, NormalizedBox
from app.main import app, streams
from app.stream import StreamSession


class DetectionWebSocketTests(unittest.TestCase):
    def setUp(self):
        streams.clear()
        self.original_mobile = settings.mobile_token
        settings.mobile_token = None

    def tearDown(self):
        settings.mobile_token = self.original_mobile
        streams.clear()

    def test_missing_stream_closes_with_4404(self):
        with TestClient(app) as client:
            with self.assertRaises(WebSocketDisconnect) as caught:
                with client.websocket_connect("/api/streams/missing/detections"):
                    pass
            self.assertEqual(caught.exception.code, 4404)

    def test_yolo_off_sends_heartbeat_without_video_subscription(self):
        streams["heartbeat"] = StreamSession("heartbeat")
        with TestClient(app) as client:
            with client.websocket_connect("/api/streams/heartbeat/detections") as websocket:
                payload = json.loads(websocket.receive_text())
                self.assertEqual(payload, {"stream_id": "heartbeat", "yolo_enabled": False})
                self.assertEqual(streams["heartbeat"].active_subscribers, 0)

    def test_mobile_token_is_required(self):
        settings.mobile_token = "mobile-secret"
        streams["secure"] = StreamSession("secure")
        with TestClient(app) as client:
            with client.websocket_connect("/api/streams/secure/detections") as websocket:
                message = websocket.receive()
                self.assertEqual(message["type"], "websocket.close")
                self.assertEqual(message["code"], 4401)

    def test_wait_detection_returns_structured_latest_result(self):
        async def scenario():
            stream = StreamSession("structured")
            stream.yolo_enabled = True
            result = InferenceResult(
                detections=(Detection(0, "person", 0.9, NormalizedBox(0.1, 0.2, 0.3, 0.4)),),
                model_id="demo",
                inference_ms=3.2,
            )
            stream.latest_detections = FrameDetections("structured", 7, 1_700_000_000_000_000, result)
            async with stream._detection_condition:
                stream._detection_version = 1
                stream._detection_condition.notify_all()
            version, latest = await stream.wait_detection(0, timeout=0.1)
            self.assertEqual(version, 1)
            self.assertEqual(latest.to_wire()["frame_seq"], 7)
            self.assertEqual(latest.to_wire()["detections"][0]["class_name"], "person")

        asyncio.run(scenario())

    def test_detection_payload_is_sent_when_yolo_enabled(self):
        stream = StreamSession("live")
        stream.yolo_enabled = True
        result = InferenceResult(
            detections=(Detection(2, "helmet", 0.8123),), model_id="m1", inference_ms=4.5
        )
        stream.latest_detections = FrameDetections("live", 3, 1_700_000_000_000_000, result)
        stream._detection_version = 1
        streams["live"] = stream
        with TestClient(app) as client:
            with client.websocket_connect("/api/streams/live/detections") as websocket:
                payload = json.loads(websocket.receive_text())
                self.assertEqual(payload["stream_id"], "live")
                self.assertEqual(payload["frame_seq"], 3)
                self.assertEqual(payload["detections"][0]["class_name"], "helmet")


if __name__ == "__main__":
    unittest.main()
