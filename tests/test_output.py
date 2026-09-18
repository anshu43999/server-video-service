import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, mjpeg_generator, streams
from app.stream import StreamSession
from tools.probe_output import sample_jpeg


class OutputContractTests(unittest.TestCase):
    def setUp(self):
        streams.clear()
        self.original_admin_token = settings.admin_token
        self.original_mobile_token = settings.mobile_token
        settings.admin_token = "output-test-admin"
        settings.mobile_token = "output-test-mobile"

    def tearDown(self):
        settings.admin_token = self.original_admin_token
        settings.mobile_token = self.original_mobile_token

    def test_mjpeg_content_type_and_websocket_jpeg(self):
        with TestClient(app) as client:
            admin_headers = {"X-Admin-Token": settings.admin_token}
            mobile_headers = {"X-Video-Service-Token": settings.mobile_token}
            stream_id = f"output-contract-{uuid.uuid4().hex}"
            try:
                self.assertEqual(client.post(
                    "/api/streams", json={"stream_id": stream_id}, headers=admin_headers
                ).status_code, 201)
                with client.websocket_connect(
                    f"/api/streams/{stream_id}/ingest", headers=mobile_headers
                ) as ingest:
                    with client.websocket_connect(
                        f"/api/streams/{stream_id}/ws", headers=admin_headers
                    ) as output:
                        ingest.send_bytes(sample_jpeg())
                        frame = output.receive_bytes()
                        self.assertTrue(frame.startswith(b"\xff\xd8"))

                async def read_part():
                    return await anext(mjpeg_generator(streams[stream_id]))

                part = asyncio.run(read_part())
                self.assertIn(b"Content-Type: image/jpeg", part)
                self.assertIn(b"Content-Length:", part)
            finally:
                client.delete(f"/api/streams/{stream_id}", headers=admin_headers)

    def test_mjpeg_generator_stops_without_replaying_last_frame_after_close(self):
        async def exercise():
            stream = StreamSession("restart-preview")
            await stream.ingest_jpeg(sample_jpeg())
            generator = mjpeg_generator(stream)
            first = await anext(generator)
            await stream.close()
            with self.assertRaises(StopAsyncIteration):
                await asyncio.wait_for(anext(generator), timeout=0.2)
            return first, stream.active_subscribers

        first, subscribers = asyncio.run(exercise())
        self.assertIn(b"Content-Type: image/jpeg", first)
        self.assertEqual(subscribers, 0)

    def test_mjpeg_response_disables_caching_and_proxy_buffering(self):
        route = next(route for route in app.routes if getattr(route, "path", None) == "/api/streams/{stream_id}/mjpeg")
        source = __import__("inspect").getsource(route.endpoint)
        self.assertIn('"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"', source)
        self.assertIn('"X-Accel-Buffering": "no"', source)


if __name__ == "__main__":
    unittest.main()
