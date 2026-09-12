from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
TEMPLATE = ROOT / "deploy" / "mediamtx" / "mediamtx.yml.example"


class MediaMTXDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = COMPOSE.read_text(encoding="utf-8")
        cls.template = TEMPLATE.read_text(encoding="utf-8")

    def test_compose_runs_pinned_mediamtx_with_restart_and_healthcheck(self):
        self.assertIn("image: bluenviron/mediamtx:1.20.1", self.compose)
        self.assertGreaterEqual(self.compose.count("restart: unless-stopped"), 2)
        self.assertIn("healthcheck:", self.compose)
        self.assertIn("condition: service_healthy", self.compose)

    def test_control_and_media_ports_are_separate(self):
        self.assertIn("CONTROL_BIND_ADDRESS:-127.0.0.1", self.compose)
        self.assertIn("MEDIA_WHEP_PORT:-8889", self.compose)
        self.assertIn("MEDIA_LLHLS_PORT:-8888", self.compose)
        self.assertIn("MEDIA_WEBRTC_UDP_PORT:-8189}:8189/udp", self.compose)
        self.assertIn("DIAGNOSTIC_RTSP_PORT:-8554", self.compose)
        self.assertIn('expose:\n      - "9997"', self.compose)
        self.assertNotIn("9997:9997", self.compose)

    def test_template_has_required_protocols_and_no_credentials(self):
        for line in (
            "api: true", "apiAddress: :9997", "rtspAddress: :8554",
            "hlsAddress: :8888", "hlsVariant: lowLatency",
            "webrtcAddress: :8889", "webrtcLocalUDPAddress: :8189",
            "paths:\n  all_others: {}",
        ):
            self.assertIn(line, self.template)
        self.assertIn("intentionally contains no credentials", self.template)

    def test_runtime_config_and_certificates_are_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("deploy/mediamtx/*.yml", ignore)
        self.assertIn("deploy/mediamtx/*.crt", ignore)
        self.assertIn("deploy/mediamtx/*.key", ignore)


if __name__ == "__main__":
    unittest.main()
