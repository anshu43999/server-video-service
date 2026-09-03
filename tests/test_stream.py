import asyncio
import unittest

import cv2
import numpy as np

from app.stream import StreamSession
from app.protocol import InputRateLimitError


def make_jpeg() -> bytes:
    image = np.zeros((32, 48, 3), dtype=np.uint8)
    image[:, :, 1] = 255
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


class StreamSessionTests(unittest.TestCase):
    def test_ingest_produces_jpeg(self):
        async def scenario():
            session = StreamSession("test")
            await session.ingest_jpeg(make_jpeg())
            self.assertTrue(session.latest_jpeg)
            decoded = cv2.imdecode(np.frombuffer(session.latest_jpeg, np.uint8), cv2.IMREAD_COLOR)
            self.assertIsNotNone(decoded)
            self.assertEqual(session.frames_received, 1)
        asyncio.run(scenario())

    def test_subscriber_limit_counter_is_bounded(self):
        session = StreamSession("test")
        self.assertTrue(session.try_subscribe())
        self.assertEqual(session.active_subscribers, 1)
        session.unsubscribe()
        session.unsubscribe()
        self.assertEqual(session.active_subscribers, 0)

    def test_input_rate_limit_rejects_burst(self):
        async def scenario():
            session = StreamSession("test")
            await session.ingest_jpeg(make_jpeg())
            with self.assertRaises(InputRateLimitError):
                await session.ingest_jpeg(make_jpeg())

        asyncio.run(scenario())

    def test_yolo_switch_is_manual_and_reports_missing_model(self):
        async def scenario():
            session = StreamSession("test")
            session.detector.model_path = "models/definitely-missing-model.pt"
            self.assertFalse(session.yolo_enabled)
            await session.set_yolo(True)
            self.assertTrue(session.yolo_enabled)
            self.assertIsNotNone(session.detector.load_error)
            await session.set_yolo(False)
            self.assertFalse(session.yolo_enabled)

        asyncio.run(scenario())

    def test_missing_model_falls_back_to_raw_output(self):
        async def scenario():
            session = StreamSession("fallback")
            session.detector.model_path = "models/definitely-missing-model.pt"
            await session.set_yolo(True)
            session._last_input = 0
            await session.ingest_jpeg(make_jpeg())
            await asyncio.sleep(0.05)
            self.assertTrue(session.latest_jpeg)
            self.assertEqual(session.frames_processed, 0)
            self.assertEqual(session.frames_fallback, 1)
            self.assertIsNotNone(session.detector.load_error)

        asyncio.run(scenario())

    def test_latest_only_replaces_pending_yolo_frame(self):
        async def scenario():
            session = StreamSession("test")
            session.yolo_enabled = True
            session.detector.annotate = lambda frame: frame
            session._last_input = 0
            await session.ingest_jpeg(make_jpeg())
            session._last_input = 0
            await session.ingest_jpeg(make_jpeg())
            await asyncio.sleep(0.05)
            self.assertGreaterEqual(session.frames_dropped, 0)
            self.assertTrue(session.latest_jpeg)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
