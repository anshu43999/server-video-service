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
        return len(payload)
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
        publisher = MediaMTXPublisher("inspection-001", PublisherConfig(enabled=True, base_url="rtsp://media:8554"))
        command = publisher.ffmpeg_command()
        self.assertEqual(command[-1], "rtsp://media:8554/inspection-001")
        self.assertIn("-c:v", command)

    def test_disabled_publisher_is_safe_noop(self):
        async def run():
            publisher = MediaMTXPublisher("idle", PublisherConfig(enabled=False))
            self.assertFalse(await publisher.publish(np.zeros((4, 4, 3), dtype=np.uint8)))
            self.assertEqual(publisher.publish_state, "idle")
        asyncio.run(run())

    def test_broken_pipe_reconnects_and_reports_failure(self):
        async def run():
            publisher = MediaMTXPublisher("reconnect", PublisherConfig(enabled=True, reconnect_delay=0, max_reconnect_attempts=1))
            with patch("app.publisher.subprocess.Popen", side_effect=[_Process(fail=True), _Process(fail=True)]), \
                 patch.object(publisher, "_ensure_encoder") as ensure:
                ensure.return_value.encode.return_value = b"\x00\x00\x00\x01\x65x"
                ok = await publisher.publish(np.zeros((4, 4, 3), dtype=np.uint8))
            self.assertFalse(ok)
            self.assertEqual(publisher.publish_state, "failed")
            self.assertIn("disconnected", publisher.last_error or "")
        asyncio.run(run())

    def test_metrics_expose_publish_state_and_viewers(self):
        publisher = MediaMTXPublisher("status", PublisherConfig(enabled=True))
        publisher.viewers = 2
        metrics = publisher.metrics()
        self.assertEqual(metrics["publish_state"], "idle")
        self.assertEqual(metrics["viewers"], 2)
        self.assertEqual(metrics["publish_path"], "status")


if __name__ == "__main__":
    unittest.main()
