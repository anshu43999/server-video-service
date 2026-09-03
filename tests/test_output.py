import unittest

from fastapi.testclient import TestClient

from app.main import app, mjpeg_generator, streams
from tools.probe_output import sample_jpeg


class OutputContractTests(unittest.TestCase):
    def setUp(self):
        streams.clear()

    def test_mjpeg_content_type_and_websocket_jpeg(self):
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/streams", json={"stream_id": "probe"}).status_code, 201)
            with client.websocket_connect("/api/streams/probe/ingest") as ingest:
                with client.websocket_connect("/api/streams/probe/ws") as output:
                    ingest.send_bytes(sample_jpeg())
                    frame = output.receive_bytes()
                    self.assertTrue(frame.startswith(b"\xff\xd8"))
            async def read_part():
                return await anext(mjpeg_generator(streams["probe"]))

            part = __import__("asyncio").run(read_part())
            self.assertIn(b"Content-Type: image/jpeg", part)
            self.assertIn(b"Content-Length:", part)


if __name__ == "__main__":
    unittest.main()
