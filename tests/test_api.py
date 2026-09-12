import asyncio
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app, streams


def make_jpeg() -> bytes:
    image = np.full((24, 32, 3), 128, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


class ApiTests(unittest.TestCase):
    def setUp(self):
        streams.clear()

    def test_create_toggle_and_ingest(self):
        with TestClient(app) as client:
            admin = client.get("/")
            self.assertEqual(admin.status_code, 200)
            # 只断言这是管理页外壳（含外壳容器与导航），不断言品牌文案：
            # 管理页改版会改标题（现为「现场智控 · 运维管理台」），改不动这两处结构。
            self.assertIn('class="app-shell"', admin.text)
            self.assertIn('id="main-nav"', admin.text)
            self.assertEqual(client.get("/admin/styles.css").status_code, 200)
            self.assertEqual(client.get("/admin/app.js").status_code, 200)
            response = client.post("/api/streams", json={"stream_id": "demo"})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["state"], "created")
            response = client.patch("/api/streams/demo/config", json={"confidence": 0.4, "max_fps": 12})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["confidence"], 0.4)
            self.assertEqual(response.json()["max_fps"], 12.0)
            self.assertTrue(response.json()["overlay_enabled"])
            response = client.patch("/api/streams/demo/config", json={"overlay_enabled": False})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["overlay_enabled"])
            self.assertFalse(streams["demo"].overlay_enabled)
            response = client.patch("/api/streams/demo/config", json={"overlay_enabled": True})
            self.assertTrue(response.json()["overlay_enabled"])
            with client.websocket_connect("/api/streams/demo/ingest") as ws:
                ws.send_bytes(make_jpeg())
            self.assertEqual(streams["demo"].frames_received, 1)
            response = client.get("/api/streams")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()[0]["stream_id"], "demo")
            self.assertEqual(response.json()[0]["state"], "outputting")
            self.assertIn("model", response.json()[0])
            self.assertIn("frames_fallback", response.json()[0])

    def test_stream_id_uses_frozen_safe_charset(self):
        with TestClient(app) as client:
            response = client.post("/api/streams", json={"stream_id": "bad/id"})
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
