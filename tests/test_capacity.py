import asyncio
import unittest

import numpy as np

from app.capacity import run_capacity_benchmark
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakePublisher:
    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.count = 0
        self.closed = False

    async def publish(self, frame):
        await asyncio.sleep(0)
        self.count += 1
        return True

    async def close(self):
        self.closed = True

    def metrics(self):
        return {"publish_state": "connected", "frames_published": self.count}


class CapacityTests(unittest.TestCase):
    def test_capacity_documentation_forbids_unencoded_capacity_reuse(self):
        docs = (ROOT / "docs" / "capacity-benchmark.md").read_text(encoding="utf-8")
        self.assertIn("H.264", docs)
        self.assertIn("不能引用 M02-T03", docs)
        self.assertIn("降级", docs)
        self.assertIn("扩容指标", docs)

    def test_runs_all_streams_concurrently_and_reports_requested_capacity(self):
        async def scenario():
            result = await run_capacity_benchmark(
                streams=3,
                frames=2,
                target_fps=1000,
                frame=np.zeros((4, 4, 3), dtype=np.uint8),
                publisher_factory=FakePublisher,
                sample_resources=lambda: {"cpu_percent": 12.0},
            )
            self.assertEqual(result.frames_requested, 6)
            self.assertEqual(result.frames_published, 6)
            self.assertEqual(len(result.per_stream), 3)
            self.assertEqual(result.resource_sample["cpu_percent"], 12.0)
            self.assertGreater(result.effective_fps, 0)
        asyncio.run(scenario())

    def test_rejects_invalid_dimensions_of_run_parameters(self):
        async def scenario():
            with self.assertRaises(ValueError):
                await run_capacity_benchmark(
                    streams=0,
                    frames=1,
                    target_fps=1,
                    frame=np.zeros((2, 2, 3), dtype=np.uint8),
                    publisher_factory=FakePublisher,
                )
        asyncio.run(scenario())

    def test_close_is_called_when_publisher_fails(self):
        class Failing(FakePublisher):
            async def publish(self, frame):
                raise RuntimeError("synthetic failure")

        async def scenario():
            with self.assertRaises(RuntimeError):
                await run_capacity_benchmark(
                    streams=1,
                    frames=1,
                    target_fps=1,
                    frame=np.zeros((2, 2, 3), dtype=np.uint8),
                    publisher_factory=Failing,
                )
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
