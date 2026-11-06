"""Remove distribution encoding, preserve input decoding/JPEG evidence."""
import importlib.util
from pathlib import Path
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class EncoderRetirementTests(unittest.TestCase):
    def test_h264_publishing_encoder_is_removed(self):
        self.assertIsNone(importlib.util.find_spec("app.encoder"))

    def test_decoder_and_preview_evidence_dependencies_remain(self):
        self.assertIn("ffmpeg", (ROOT / "Dockerfile").read_text(encoding="utf-8"))
        self.assertIn("opencv-python-headless", (ROOT / "requirements.txt").read_text(encoding="utf-8"))
        ok, encoded = cv2.imencode(".jpg", np.zeros((24, 32, 3), dtype=np.uint8))
        self.assertTrue(ok)
        self.assertEqual((24, 32, 3), cv2.imdecode(encoded, cv2.IMREAD_COLOR).shape)


if __name__ == "__main__":
    unittest.main()
