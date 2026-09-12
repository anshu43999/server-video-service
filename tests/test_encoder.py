import unittest
from unittest.mock import patch

import numpy as np

from app.encoder import EncoderConfig, EncoderUnavailableError, H264Encoder


class EncoderConfigTests(unittest.TestCase):
    def test_constraints_and_gop(self):
        cfg = EncoderConfig(1280, 720, fps=25, profile="Main", level="4.0", gop_seconds=2)
        self.assertEqual(cfg.gop_frames, 50)

    def test_rejects_unsupported_constraints(self):
        with self.assertRaises(ValueError):
            EncoderConfig(10, 10, level="4.1")
        with self.assertRaises(ValueError):
            EncoderConfig(10, 10, gop_seconds=0.5)


class H264EncoderTests(unittest.TestCase):
    def test_ffmpeg_command_contains_low_latency_constraints(self):
        enc = H264Encoder(EncoderConfig(4, 4, fps=25), backend="ffmpeg", ffmpeg_path="ffmpeg.exe")
        command = enc.ffmpeg_command()
        for token in ("-profile:v", "baseline", "-level:v", "4.0", "-bf", "0", "-g", "50", "-tune", "zerolatency"):
            self.assertIn(token, command)

    @patch("app.encoder.subprocess.run")
    def test_encode_records_metrics(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = b"\x00\x00\x00\x01\x65encoded"
        run.return_value.stderr = b""
        enc = H264Encoder(EncoderConfig(4, 4), backend="ffmpeg", ffmpeg_path="ffmpeg.exe")
        output = enc.encode(np.zeros((4, 4, 3), dtype=np.uint8))
        self.assertTrue(output.startswith(b"\x00\x00\x00\x01"))
        self.assertEqual(enc.metrics.frames_encoded, 1)
        self.assertIsNotNone(enc.metrics.last_encode_ms)
        run.assert_called_once()

    @patch("app.encoder.subprocess.run")
    def test_encode_failure_is_structured(self, run):
        run.return_value.returncode = 1
        run.return_value.stdout = b""
        run.return_value.stderr = b"Unknown encoder"
        enc = H264Encoder(EncoderConfig(4, 4), backend="ffmpeg", ffmpeg_path="ffmpeg.exe")
        with self.assertRaisesRegex(EncoderUnavailableError, "Unknown encoder"):
            enc.encode(np.zeros((4, 4, 3), dtype=np.uint8))


if __name__ == "__main__":
    unittest.main()
