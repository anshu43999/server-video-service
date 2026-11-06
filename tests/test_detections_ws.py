"""Raw per-frame detections are internal; clients consume formal project alerts."""
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import app

class DetectionWebSocketTests(unittest.TestCase):
    def test_all_detection_subscriptions_fail_without_project_or_stream_lookup(self):
        with nullcontext(TestClient(app)) as client, patch("app.main.resolve_websocket_project_context", side_effect=AssertionError("resource lookup")):
            for prefix in ("/aiyoloapi/streams", "/aiyoloapi/projects/unknown/streams"):
                for token in (None, "old-session", "another-project"):
                    headers = {"Authorization": "Bearer " + token} if token else {}
                    with self.subTest(prefix=prefix, token=token):
                        with self.assertRaises(WebSocketDisconnect) as caught:
                            with client.websocket_connect(prefix + "/camera/detections", headers=headers):
                                self.fail("retired detection subscription accepted")
                        self.assertEqual(1008, caught.exception.code)
                        self.assertEqual("live_video_retired", caught.exception.reason)
