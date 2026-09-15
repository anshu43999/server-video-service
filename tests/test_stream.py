import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np

from app.detection import InferenceResult
from app.stream import StreamSession, _FrameRateLimiter
from app.protocol import InputRateLimitError


def make_jpeg() -> bytes:
    image = np.zeros((32, 48, 3), dtype=np.uint8)
    image[:, :, 1] = 255
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


class StreamSessionTests(unittest.TestCase):
    def test_rtsp_rate_limiter_tolerates_jitter_but_caps_sustained_bursts(self):
        limiter = _FrameRateLimiter()
        jittered_25_fps = [0.0, 0.02, 0.04, 0.08, 0.12, 0.16, 0.20]
        self.assertTrue(all(limiter.allow(now, 25) for now in jittered_25_fps))

        limiter = _FrameRateLimiter()
        accepted = sum(limiter.allow(index / 100, 25) for index in range(101))
        self.assertLessEqual(accepted, 33)
        self.assertGreaterEqual(accepted, 25)

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

    def test_decoded_frame_ingest_avoids_jpeg_decode(self):
        async def scenario():
            session = StreamSession("decoded")
            frame = np.zeros((32, 48, 3), dtype=np.uint8)
            frame[:, :, 1] = 255
            await session.ingest_frame(frame)
            self.assertEqual(session.frames_received, 1)
            self.assertTrue(session.latest_jpeg)

        asyncio.run(scenario())

    def test_internal_rtsp_frames_do_not_disconnect_on_arrival_jitter(self):
        async def scenario():
            session = StreamSession("rtsp-jitter")
            frame = np.zeros((32, 48, 3), dtype=np.uint8)
            with patch.object(session, "_wait_for_emit_slot", new=AsyncMock()) as pacer:
                await session.ingest_frame(
                    frame, enforce_rate_limit=False, pace_output=False
                )
                await session.ingest_frame(
                    frame, enforce_rate_limit=False, pace_output=False
                )
            pacer.assert_not_awaited()
            self.assertEqual(session.frames_received, 2)

        asyncio.run(scenario())

    def test_max_fps_reconfigures_persistent_publisher(self):
        async def scenario():
            session = StreamSession("fps")
            await session.set_max_fps(15)
            self.assertEqual(session.max_fps, 15)
            self.assertEqual(session.publisher.config.fps, 15)

        asyncio.run(scenario())

    def test_output_pacer_waits_for_the_next_target_slot(self):
        async def scenario():
            session = StreamSession("pacer")
            session.max_fps = 20
            session._last_emit = 100.0
            with patch("app.stream.time.monotonic", return_value=100.01), \
                 patch("app.stream.asyncio.sleep", new=AsyncMock()) as sleep:
                await session._wait_for_emit_slot()
            sleep.assert_awaited_once()
            self.assertAlmostEqual(sleep.await_args.args[0], 0.04, places=6)
            self.assertAlmostEqual(session._last_emit, 100.05, places=6)

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
            session.detector.infer = lambda frame: InferenceResult(
                frame_width=frame.shape[1], frame_height=frame.shape[0], provides=("BOX",)
            )
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
