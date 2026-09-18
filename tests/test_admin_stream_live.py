from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminStreamLiveContractTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        self.start_script = (ROOT / "start-server.ps1").read_text(encoding="utf-8")
        self.yolo_requirements = (ROOT / "requirements-yolo.txt").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_live_create_submits_stream_id_and_source_url(self):
        for marker in ('id="source-url"', 'id="new-stream-status"', 'id="create-stream-submit"'):
            self.assertIn(marker, self.html)
        self.assertIn("fetch('/api/streams',{method:'POST'", self.js)
        self.assertIn("source_url:source||null", self.js)
        self.assertIn("await refreshLiveStreams()", self.js)

    def test_persisted_configuration_and_runtime_states_are_distinct(self):
        self.assertIn("runtime_available", self.js)
        self.assertIn("runtime_state", self.js)
        self.assertIn("source_url||s.source", self.js)
        self.assertIn("配置停用", self.js)
        self.assertIn("等待恢复", self.js)
        self.assertIn("stream-enabled-toggle", self.html)
        self.assertIn("updateSelectedStreamConfig({enabled:desired})", self.js)
        self.assertIn("if(!saved)input.checked=previous", self.js)
        self.assertIn("body?.detail?.message", self.js)
        self.assertIn("app.js?v=20260917-stream-preview-stale-frame", self.html)

    def test_live_preview_uses_authenticated_same_origin_mjpeg(self):
        self.assertIn("`/api/streams/${encodeURIComponent(stream.stream_id)}/mjpeg?connection=${Date.now()}`", self.js)
        self.assertIn("state.demo?STREAM_PREVIEW_IMAGES", self.js)
        self.assertNotIn("previewImage.src=STREAM_PREVIEW_IMAGES", self.js)

    def test_live_preview_reconnects_after_stream_is_reenabled(self):
        unavailable_branch = self.js.split(
            "if(!state.demo&&stream.runtime_available===false){", 1
        )[1].split("return;}", 1)[0]
        self.assertIn("image.removeAttribute('src')", unavailable_branch)
        self.assertIn("delete image.dataset.previewKey", unavailable_branch)
        self.assertNotIn("image.dataset.previewKey=previewKey", unavailable_branch)
        self.assertIn(
            "image.onerror=()=>{image.classList.add('hidden');delete image.dataset.previewKey;",
            self.js,
        )
        self.assertIn("mjpeg?connection=${Date.now()}", self.js)

    def test_video_previews_preserve_the_complete_frame(self):
        self.assertRegex(
            self.css,
            r"\.stream-preview-image\{[^}]*object-fit:contain[^}]*background:#0b1210",
        )
        self.assertRegex(
            self.css,
            r"\.dashboard-stream-media img\{[^}]*object-fit:contain[^}]*background:#0b1210",
        )

    def test_stream_preview_hides_prototype_decorations(self):
        for selector in (
            ".fake-preview::before",
            ".fake-preview::after",
            ".fake-preview .scan-line",
            ".fake-preview .camera-glyph",
        ):
            self.assertIn(selector, self.css)
        self.assertRegex(
            self.css,
            r"\.fake-preview::before,[\s\S]*?\.fake-preview \.camera-glyph\{\s*display:none;\s*\}",
        )
        self.assertIn("styles.css?v=20260917-clean-stream-preview", self.html)

    def test_live_controls_call_stream_management_apis(self):
        self.assertIn("}/yolo`,{method:'POST'", self.js)
        self.assertIn("}/config`,{method:'PATCH'", self.js)
        self.assertIn("}`,{method:'DELETE'}", self.js)
        self.assertIn("$('refresh-btn').onclick=()=>state.demo?", self.js)
        self.assertIn("if(!state.streams.some(s=>s.stream_id===state.selected))", self.js)

    def test_demo_mutations_remain_local(self):
        self.assertIn("if(state.demo){state.streams.push", self.js)
        self.assertIn("if(state.demo){s.yolo_enabled=e.target.checked", self.js)
        self.assertIn("if(state.demo){Object.assign(s,values)", self.js)

    def test_windows_launcher_can_manage_local_media_plane(self):
        for marker in (
            "[switch]$WithMediaMtx",
            '[string]$MediaPublicHost = "127.0.0.1"',
            '[string]$MediaBindAddress = "127.0.0.1"',
            '$env:MEDIAMTX_ENABLED = "true"',
            '$env:MEDIAMTX_RTSP_URL = "rtsp://127.0.0.1:$MediaRtspPort"',
            '$env:MEDIAMTX_WHEP_URL = "http://${MediaPublicHost}:$MediaWhepPort"',
            '$env:MEDIAMTX_LLHLS_URL = "http://${MediaPublicHost}:$MediaHlsPort"',
            "hlsAddress: ${MediaBindAddress}:$MediaHlsPort",
            "webrtcAddress: ${MediaBindAddress}:$MediaWhepPort",
            "webrtcLocalUDPAddress: ${MediaBindAddress}:$MediaWebRtcUdpPort",
            "webrtcAdditionalHosts: [$MediaPublicHost]",
            "Stop-ManagedProcess $mediaProcess",
        ):
            self.assertIn(marker, self.start_script)
        self.assertIn(".\\start-server.ps1 -WithMediaMtx", self.readme)
        self.assertIn("-MediaBindAddress 0.0.0.0 -MediaPublicHost 10.0.2.2", self.readme)
        self.assertIn("192.168.1.210", self.readme)
        self.assertIn("rtsp://127.0.0.1:18554/file-test", self.readme)

    def test_yolo_runtime_keeps_opencv_on_supported_major_version(self):
        self.assertIn("opencv-python>=4.10,<5", self.yolo_requirements)
        self.assertIn("int(cv2.__version__.split('.')[0]) < 5", self.start_script)
        self.assertIn('pip install "opencv-python>=4.10,<5"', self.start_script)


if __name__ == "__main__":
    unittest.main()
