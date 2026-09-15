import asyncio
import unittest
from unittest.mock import patch

import numpy as np

from app.publisher import MediaMTXPublisher, PublisherConfig


class _Pipe:
    def __init__(self, fail=False):
        self.fail = fail
    def write(self, payload):
        if self.fail:
            raise BrokenPipeError("media server disconnected")
        return payload.nbytes if hasattr(payload, "nbytes") else len(payload)
    def flush(self):
        return None
    def close(self):
        return None


class _Process:
    def __init__(self, fail=False):
        self.stdin = _Pipe(fail)
        self.returncode = None
    def poll(self):
        return self.returncode
    def terminate(self):
        self.returncode = 0
    def wait(self, timeout=None):
        self.returncode = 0
    def kill(self):
        self.returncode = 0


class PublisherTests(unittest.TestCase):
    def test_fixed_path_command(self):
        publisher = MediaMTXPublisher(
            "inspection-001",
            PublisherConfig(enabled=True, base_url="rtsp://media:8554", encoder="libx264"),
        )
        command = publisher.ffmpeg_command(1280, 720)
        self.assertEqual(command[-1], "rtsp://media:8554/inspection-001")
        for marker in ("rawvideo", "yuv420p", "1280x720", "libx264", "ultrafast", "zerolatency", "6000k"):
            self.assertIn(marker, command)

    def test_auto_encoder_prefers_qsv_and_exposes_software_fallback_command(self):
        publisher = MediaMTXPublisher("hardware", PublisherConfig(enabled=True, encoder="auto"))
        self.assertIn("h264_qsv", publisher.ffmpeg_command(1280, 720))
        self.assertIn("format=nv12", publisher.ffmpeg_command(1280, 720))
        self.assertIn("libx264", publisher.ffmpeg_command(1280, 720, "libx264"))

    def test_invalid_encoder_is_rejected(self):
        with self.assertRaises(ValueError):
            PublisherConfig(encoder="not-an-encoder")

    def test_reuses_one_ffmpeg_process_for_consecutive_frames(self):
        async def run():
            publisher = MediaMTXPublisher("persistent", PublisherConfig(enabled=True))
            process = _Process()
            with patch("app.publisher.subprocess.Popen", return_value=process) as popen:
                frame = np.zeros((4, 6, 3), dtype=np.uint8)
                self.assertTrue(await publisher.publish(frame))
                self.assertTrue(await publisher.publish(frame))
            popen.assert_called_once()
            self.assertEqual(publisher.frames_published, 2)
            self.assertEqual(publisher._frame_size, (6, 4))
        asyncio.run(run())

    def test_resolution_change_restarts_ffmpeg(self):
        async def run():
            publisher = MediaMTXPublisher("resize", PublisherConfig(enabled=True))
            first, second = _Process(), _Process()
            with patch("app.publisher.subprocess.Popen", side_effect=[first, second]) as popen:
                await publisher.publish(np.zeros((4, 6, 3), dtype=np.uint8))
                await publisher.publish(np.zeros((8, 10, 3), dtype=np.uint8))
            self.assertEqual(popen.call_count, 2)
            self.assertEqual(first.returncode, 0)
            self.assertEqual(publisher._frame_size, (10, 8))
        asyncio.run(run())

    def test_disabled_publisher_is_safe_noop(self):
        async def run():
            publisher = MediaMTXPublisher("idle", PublisherConfig(enabled=False))
            self.assertFalse(await publisher.publish(np.zeros((4, 4, 3), dtype=np.uint8)))
            self.assertEqual(publisher.publish_state, "idle")
        asyncio.run(run())

    def test_broken_pipe_reconnects_and_reports_failure(self):
        async def run():
            publisher = MediaMTXPublisher("reconnect", PublisherConfig(enabled=True, reconnect_delay=0, max_reconnect_attempts=1))
            with patch("app.publisher.subprocess.Popen", side_effect=[_Process(fail=True), _Process(fail=True)]):
                ok = await publisher.publish(np.zeros((4, 4, 3), dtype=np.uint8))
            self.assertFalse(ok)
            self.assertEqual(publisher.publish_state, "failed")
            self.assertIn("disconnected", publisher.last_error or "")
        asyncio.run(run())

    def test_auto_encoder_falls_back_when_qsv_fails_during_startup(self):
        async def run():
            publisher = MediaMTXPublisher(
                "fallback", PublisherConfig(enabled=True, reconnect_delay=0, max_reconnect_attempts=1)
            )
            with patch("app.publisher.subprocess.Popen", side_effect=[_Process(fail=True), _Process()]) as popen:
                self.assertTrue(await publisher.publish(np.zeros((4, 4, 3), dtype=np.uint8)))
            self.assertEqual(popen.call_count, 2)
            self.assertEqual(publisher.active_encoder, "libx264")

        asyncio.run(run())

    def test_metrics_expose_publish_state_and_viewers(self):
        publisher = MediaMTXPublisher("status", PublisherConfig(enabled=True))
        publisher.viewers = 2
        metrics = publisher.metrics()
        self.assertEqual(metrics["publish_state"], "idle")
        self.assertEqual(metrics["viewers"], 2)
        self.assertEqual(metrics["publish_path"], "status")

    def test_viewer_refresh_is_throttled(self):
        async def run():
            publisher = MediaMTXPublisher(
                "viewers", PublisherConfig(enabled=True, api_url="http://media:9997")
            )
            response = unittest.mock.MagicMock()
            response.__enter__.return_value.read.return_value = b'{"items": []}'
            with patch("app.publisher.urllib.request.urlopen", return_value=response) as request:
                await publisher.refresh_viewers()
                await publisher.refresh_viewers()
            request.assert_called_once()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
