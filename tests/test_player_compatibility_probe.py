import json
import subprocess
import sys
import unittest
from pathlib import Path

from tools.player_compatibility_probe import percentile, probe_rtsp, probe_whep


class PlayerCompatibilityProbeTests(unittest.TestCase):
    def test_percentile_is_deterministic(self):
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertIsNone(percentile([], 0.95))

    def test_whep_without_browser_offer_is_blocked(self):
        result = probe_whep("http://127.0.0.1:8889/cam/whep", None, 1, 0.1)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("SDP offer", result["reason"])

    def test_rtsp_without_ffprobe_is_blocked(self):
        result = probe_rtsp("rtsp://127.0.0.1:8554/cam", "definitely-missing-ffprobe", 0.1)
        self.assertEqual(result["status"], "blocked")

    def test_cli_marks_missing_endpoints_frozen(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run([sys.executable, str(root / "tools/player_compatibility_probe.py")], capture_output=True, text=True, check=True)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["frozen"])
        self.assertEqual(payload["whep"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
