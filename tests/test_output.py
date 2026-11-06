"""ADR-003: live MJPEG/JPEG output is retired, evidence media is unaffected."""
import asyncio
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import app
from app.stream import StreamSession

class OutputContractTests(unittest.TestCase):
    def test_mjpeg_has_no_frame_output(self):
        with nullcontext(TestClient(app)) as client, patch("app.main.get_stream", side_effect=AssertionError("resource lookup")):
            for prefix in ("/aiyoloapi/streams", "/aiyoloapi/projects/unknown/streams"):
                response = client.get(prefix + "/camera/mjpeg")
                self.assertEqual(410, response.status_code, response.text)
                self.assertNotIn("multipart", response.headers["content-type"])
                self.assertIn("no-store", response.headers["cache-control"])

    def test_jpeg_websocket_cannot_subscribe_or_receive_frames(self):
        with nullcontext(TestClient(app)) as client:
            for prefix in ("/aiyoloapi/streams", "/aiyoloapi/projects/unknown/streams"):
                with self.assertRaises(WebSocketDisconnect) as caught:
                    with client.websocket_connect(prefix + "/camera/ws"):
                        self.fail("retired WebSocket accepted")
                self.assertEqual(1008, caught.exception.code)

    def test_internal_preview_hooks_are_inert_before_and_after_close(self):
        async def check():
            stream = StreamSession("camera")
            self.assertFalse(stream.try_subscribe())
            self.assertIsNone(await stream.wait_frame())
            await stream.close()
            self.assertIsNone(await stream.wait_frame())
            self.assertEqual(0, stream.active_subscribers)
        asyncio.run(check())
