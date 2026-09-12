from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminOutputContractTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    def test_stream_inspector_exposes_protocol_urls_and_diagnostic_label(self):
        for marker in ("whep-url", "hls-url", "rtsp-url", "诊断预览：MJPEG / WebSocket JPEG"):
            self.assertIn(marker, self.html)

    def test_live_adapter_reads_playback_and_detection_side_channel(self):
        self.assertIn("/api/streams/${encodeURIComponent(stream.stream_id)}/playback", self.js)
        self.assertIn("/api/streams/${encodeURIComponent(stream.stream_id)}/detections", self.js)
        self.assertIn("state.playback", self.js)
        self.assertIn("WebSocket", self.js)

    def test_rtsp_is_rendered_as_diagnostics_only(self):
        self.assertIn("txt('rtsp-state','诊断通道')", self.js)
        self.assertIn("生产播放请使用 WHEP，LL-HLS 为回退", self.html)


if __name__ == "__main__":
    unittest.main()
