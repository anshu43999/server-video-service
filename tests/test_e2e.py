import unittest
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app, streams


def frame_jpeg(value: int) -> bytes:
    frame = np.full((48, 64, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    return encoded.tobytes()


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        streams.clear()

    def test_multiple_real_frames_round_trip_and_state(self):
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/streams", json={"stream_id": "e2e"}).status_code, 201)
            with client.websocket_connect("/api/streams/e2e/ingest") as ingest:
                with client.websocket_connect("/api/streams/e2e/ws") as output:
                    for value in (10, 80, 160, 240):
                        ingest.send_bytes(frame_jpeg(value))
                        received = output.receive_bytes()
                        self.assertTrue(received.startswith(b"\xff\xd8"))
                        time.sleep(0.06)
            details = client.get("/api/streams").json()[0]
            self.assertEqual(details["frames_received"], 4)
            self.assertEqual(details["state"], "outputting")


if __name__ == "__main__":
    unittest.main()
