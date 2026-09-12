"""Deterministic fault-injection checks for the M04-T04 recovery runbook.

These tests do not claim a real MediaMTX or network measurement.  They inject
the same failures that the publisher sees at its process pipe and assert the
state/resource invariants which must also be checked during a deployment run.
"""

import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.publisher import MediaMTXPublisher, PublisherConfig
from app.stream import StreamSession


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "fault-recovery.md"


class _Pipe:
    def __init__(self, failures: int = 0):
        self.failures = failures
        self.closed = False

    def write(self, payload):
        if self.failures:
            self.failures -= 1
            raise BrokenPipeError("injected packet loss / media restart")
        return len(payload)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class _Process:
    def __init__(self, pipe):
        self.stdin = pipe
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        self.returncode = 0

    def kill(self):
        self.returncode = 0


class FaultRecoveryTests(unittest.TestCase):
    def test_runbook_covers_required_faults_and_no_fake_measurements(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        for marker in (
            "断流", "丢包", "播放器断开", "WHEP", "LL-HLS", "服务重启",
            "MediaMTX 重启", "资源泄漏", "docker compose stop mediamtx",
            "docker compose restart mediamtx", "不得伪造",
        ):
            self.assertIn(marker, text)

    def test_transient_media_restart_reconnects_and_keeps_stream_connected(self):
        async def run():
            publisher = MediaMTXPublisher(
                "weak-network", PublisherConfig(enabled=True, reconnect_delay=0, max_reconnect_attempts=2)
            )
            first = _Process(_Pipe(failures=1))
            second = _Process(_Pipe(failures=0))
            with patch("app.publisher.subprocess.Popen", side_effect=[first, second]), \
                 patch.object(publisher, "_ensure_encoder") as ensure:
                ensure.return_value.encode.return_value = b"\x00\x00\x00\x01\x65"
                ok = await publisher.publish(np.zeros((4, 4, 3), dtype=np.uint8))
            self.assertTrue(ok)
            self.assertEqual(publisher.publish_state, "connected")
            self.assertEqual(publisher.frames_published, 1)
            await publisher.close()
            self.assertEqual(publisher.publish_state, "idle")
            self.assertIsNone(publisher._process)

        asyncio.run(run())

    def test_exhausted_reconnect_is_failed_then_close_releases_process(self):
        async def run():
            publisher = MediaMTXPublisher(
                "media-restart", PublisherConfig(enabled=True, reconnect_delay=0, max_reconnect_attempts=1)
            )
            with patch("app.publisher.subprocess.Popen", side_effect=[_Process(_Pipe(9)), _Process(_Pipe(9))]), \
                 patch.object(publisher, "_ensure_encoder") as ensure:
                ensure.return_value.encode.return_value = b"\x00\x00\x00\x01\x65"
                self.assertFalse(await publisher.publish(np.zeros((4, 4, 3), dtype=np.uint8)))
            self.assertEqual(publisher.publish_state, "failed")
            await publisher.close()
            self.assertEqual(publisher.publish_state, "idle")
            self.assertIsNone(publisher._process)

        asyncio.run(run())

    def test_player_disconnect_and_session_shutdown_leave_no_subscribers_or_tasks(self):
        async def run():
            session = StreamSession("player-disconnect")
            self.assertTrue(session.try_subscribe())
            self.assertEqual(session.active_subscribers, 1)
            session.unsubscribe()
            self.assertEqual(session.active_subscribers, 0)
            session._processing_task = asyncio.create_task(asyncio.sleep(60))
            await session.close()
            self.assertTrue(session.closed)
            self.assertEqual(session.active_subscribers, 0)
            self.assertIsNone(session.publisher._process)
            self.assertTrue(session._processing_task.done())

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
