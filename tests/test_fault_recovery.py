"""Local shutdown checks; real source/network soak remains M34-T06."""
import asyncio
import unittest
from pathlib import Path

from app.stream import StreamSession

ROOT = Path(__file__).resolve().parents[1]


class FaultRecoveryTests(unittest.TestCase):
    def test_runbook_covers_current_faults_without_fake_measurements(self):
        text = (ROOT / "docs/fault-recovery.md").read_text(encoding="utf-8")
        for marker in ("断流", "丢包", "PC预览", "无人观看", "服务重启", "资源泄漏", "不得伪造", "M34-T06"):
            self.assertIn(marker, text)
        self.assertNotIn("docker compose restart mediamtx", text)

    def test_session_shutdown_leaves_no_subscribers_or_tasks(self):
        async def run():
            session = StreamSession("player-disconnect")
            self.assertFalse(session.try_subscribe())
            self.assertEqual(session.active_subscribers, 0)
            session.unsubscribe()
            session._processing_task = asyncio.create_task(asyncio.sleep(60))
            await session.close()
            self.assertTrue(session.closed)
            self.assertEqual(session.active_subscribers, 0)
            self.assertFalse(hasattr(session, "publisher"))
            self.assertTrue(session._processing_task.done())
            self.assertIsNone(await session.admin_preview())

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
