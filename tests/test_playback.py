import unittest

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, streams
from app.stream import StreamSession


class PlaybackApiTests(unittest.TestCase):
    def setUp(self):
        streams.clear()
        self.original = {
            "mediamtx_enabled": settings.mediamtx_enabled,
            "mediamtx_rtsp_url": settings.mediamtx_rtsp_url,
            "mediamtx_whep_url": settings.mediamtx_whep_url,
            "mediamtx_llhls_url": settings.mediamtx_llhls_url,
            "mediamtx_http_scheme": settings.mediamtx_http_scheme,
        }

    def tearDown(self):
        streams.clear()
        for name, value in self.original.items():
            setattr(settings, name, value)

    def test_missing_stream_returns_404(self):
        with TestClient(app) as client:
            response = client.get("/api/streams/missing/playback")
        self.assertEqual(response.status_code, 404)

    def test_unpublished_stream_exposes_unavailable_protocols(self):
        settings.mediamtx_enabled = True
        settings.mediamtx_rtsp_url = "rtsp://media.example:8554"
        streams["inspection-001"] = StreamSession("inspection-001")
        with TestClient(app) as client:
            payload = client.get("/api/streams/inspection-001/playback").json()
        self.assertEqual(payload["publish_state"], "idle")
        self.assertEqual(payload["whep"], {"url": "http://media.example:8889/inspection-001/whep", "available": False})
        self.assertEqual(payload["llhls"], {"url": "http://media.example:8888/inspection-001/index.m3u8", "available": False})
        self.assertFalse(payload["rtsp"]["available"])
        self.assertTrue(payload["rtsp"]["diagnostics_only"])

    def test_connected_stream_reports_all_protocols_available(self):
        settings.mediamtx_enabled = True
        settings.mediamtx_rtsp_url = "rtsp://user:secret@[2001:db8::10]:8554"
        settings.mediamtx_whep_url = "https://video.example/webrtc"
        settings.mediamtx_llhls_url = "https://video.example/hls"
        stream = StreamSession("inspection-002")
        stream.publisher.publish_state = "connected"
        streams[stream.stream_id] = stream
        with TestClient(app) as client:
            payload = client.get("/api/streams/inspection-002/playback").json()
        self.assertEqual(payload["publish_state"], "connected")
        self.assertTrue(payload["whep"]["available"])
        self.assertEqual(payload["whep"]["url"], "https://video.example/webrtc/inspection-002/whep")
        self.assertEqual(payload["llhls"]["url"], "https://video.example/hls/inspection-002/index.m3u8")
        # The diagnostic address follows the configured RTSP origin, including
        # any deployment-specific credentials required by the media server.
        self.assertEqual(payload["rtsp"]["url"], "rtsp://user:secret@[2001:db8::10]:8554/inspection-002")
        self.assertTrue(payload["rtsp"]["diagnostics_only"])

    def test_failed_state_is_not_available(self):
        settings.mediamtx_enabled = True
        stream = StreamSession("failed")
        stream.publisher.publish_state = "failed"
        streams["failed"] = stream
        with TestClient(app) as client:
            payload = client.get("/api/streams/failed/playback").json()
        self.assertEqual(payload["publish_state"], "failed")
        self.assertFalse(payload["whep"]["available"])
        self.assertFalse(payload["llhls"]["available"])
        self.assertFalse(payload["rtsp"]["available"])


if __name__ == "__main__":
    unittest.main()
