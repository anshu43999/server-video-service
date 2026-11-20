import time
import unittest

import cv2
import numpy as np
from starlette.websockets import WebSocketDisconnect

from stream_api_support import StreamApiFixture


def frame_jpeg(value: int) -> bytes:
    frame = np.full((48, 64, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode('.jpg', frame)
    assert ok
    return encoded.tobytes()


class EndToEndTests(StreamApiFixture, unittest.TestCase):
    def test_multiple_real_frames_round_trip_and_state(self):
        self.create_stream('e2e')
        path = self.streams_path + '/e2e'
        with self.client.websocket_connect(path + '/ingest') as ingest:
            for value in (10, 80, 160, 240):
                ingest.send_bytes(frame_jpeg(value))
                # The serial ingest reply proves decoding finished before preview.
                ingest.send_text('processed-barrier')
                self.assertTrue(ingest.receive_json()['ok'])
                deadline = time.monotonic() + 2
                while True:
                    response = self.client.get(path + '/preview')
                    self.assertEqual(200, response.status_code, response.text)
                    self.assertEqual('image/jpeg', response.headers['content-type'])
                    self.assertEqual('raw', response.headers['x-preview-mode'])
                    decoded = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
                    self.assertEqual((48, 64, 3), decoded.shape)
                    if abs(float(decoded.mean()) - value) <= 2:
                        break
                    if time.monotonic() >= deadline:
                        self.fail('preview did not advance to the newly ingested frame')
                    time.sleep(0.05)  # Preview encoding is intentionally capped.
                time.sleep(0.04)  # Stay below the input-frame limit.
        details = self.client.get(self.streams_path).json()[0]
        self.assertEqual(details['project_id'], self.project_id)
        self.assertEqual(details['frames_received'], 4)
        self.assertEqual(details['state'], 'ingesting')
        self.assertEqual(details['frames_processed'], 0)
        self.assertEqual(403, self.client.get(path + '/preview', headers=self.headers).status_code)
        with self.assertRaises(WebSocketDisconnect) as closed:
            with self.client.websocket_connect(path + '/ws'):
                self.fail('retired distribution websocket unexpectedly accepted')
        self.assertEqual(1008, closed.exception.code)


if __name__ == '__main__':
    unittest.main()
