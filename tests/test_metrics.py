import asyncio
import unittest

from app.stream import StreamSession
from test_stream import make_jpeg


class MetricsTests(unittest.TestCase):
    def test_metrics_are_exposed_after_frame(self):
        async def scenario():
            session = StreamSession("metrics")
            await session.ingest_jpeg(make_jpeg())
            metrics = session.metrics()
            self.assertEqual(metrics["frames_received"], 1)
            self.assertIn("output_fps", metrics)
            self.assertIn("active_subscribers", metrics)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
