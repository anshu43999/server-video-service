import unittest

import cv2
import numpy as np

import app.main as main
from stream_api_support import StreamApiFixture


def make_jpeg() -> bytes:
    image = np.full((24, 32, 3), 128, dtype=np.uint8)
    ok, encoded = cv2.imencode('.jpg', image)
    assert ok
    return encoded.tobytes()


class ApiTests(StreamApiFixture, unittest.TestCase):
    def test_create_toggle_and_ingest(self):
        client = self.client
        admin = client.get('/')
        self.assertEqual(admin.status_code, 200)
        self.assertEqual(client.get('/', follow_redirects=False).headers['location'], '/admin/')
        self.assertIn('id="app"', admin.text)
        self.assertIn('/admin/assets/', admin.text)
        self.assertEqual(client.get('/admin/styles.css').status_code, 404)
        self.assertEqual(client.get('/admin/app.js').status_code, 404)
        response = self.create_stream('demo')
        self.assertEqual(response.json()['state'], 'created')
        stream_path = self.streams_path + '/demo'
        confidence = response.json()['confidence']
        # A stream cannot override the scene's reviewed confidence threshold.
        rejected = client.patch(stream_path + '/config', json={
            'confidence': 0.99 if confidence != 0.99 else 0.01})
        self.assertEqual(409, rejected.status_code, rejected.text)
        self.assertEqual('parameter_approval_required', rejected.json()['detail']['code'])
        response = client.patch(stream_path + '/config', json={'confidence': confidence, 'max_fps': 12})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(response.json()['confidence'], confidence)
        self.assertEqual(response.json()['max_fps'], 12.0)
        self.assertTrue(response.json()['overlay_enabled'])
        response = client.patch(stream_path + '/config', json={'overlay_enabled': False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['overlay_enabled'])
        self.assertFalse(main.streams[(self.project_id, 'demo')].overlay_enabled)
        response = client.patch(stream_path + '/config', json={'overlay_enabled': True})
        self.assertTrue(response.json()['overlay_enabled'])
        with client.websocket_connect(stream_path + '/ingest') as ws:
            ws.send_bytes(make_jpeg())
            ws.send_text('processed-barrier')
            self.assertTrue(ws.receive_json()['ok'])
        self.assertEqual(main.streams[(self.project_id, 'demo')].frames_received, 1)
        response = client.get(self.streams_path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['stream_id'], 'demo')
        self.assertEqual(response.json()[0]['state'], 'ingesting')
        self.assertIn('model', response.json()[0])
        self.assertIn('frames_fallback', response.json()[0])

    def test_stream_id_uses_frozen_safe_charset(self):
        response = self.client.post(self.streams_path, json={
            'stream_id': 'bad/id', **self.selection})
        self.assertEqual(response.status_code, 422)

    def test_stream_creation_requires_explicit_approved_scene(self):
        response = self.client.post(self.streams_path, json={'stream_id': 'unapproved'})
        self.assertEqual(422, response.status_code)
        self.assertNotIn((self.project_id, 'unapproved'), main.streams)


if __name__ == '__main__':
    unittest.main()
