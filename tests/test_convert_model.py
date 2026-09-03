import argparse
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import convert_model


class _FakeModel:
    def __init__(self, weights):
        self.weights = weights

    def export(self, **kwargs):
        if kwargs["format"] == "onnx":
            output = Path(self.weights).with_suffix(".onnx")
            output.write_bytes(b"onnx-artifact")
            return str(output)
        raise AssertionError("LiteRT export only supported on Linux x86 and macOS")


class ConvertModelTests(unittest.TestCase):
    TEST_ROOT = Path(__file__).resolve().parents[1] / ".test-convert"

    @classmethod
    def setUpClass(cls):
        cls.TEST_ROOT.mkdir(parents=True, exist_ok=True)

    def _args(self, weights: Path, output_dir: Path, fmt="server", server_format="both"):
        return argparse.Namespace(
            weights=weights,
            output_dir=output_dir,
            format=fmt,
            server_format=server_format,
            imgsz=640,
        )

    def test_server_conversion_can_keep_pt_and_export_onnx(self):
        root = self.TEST_ROOT / "server"
        root.mkdir(parents=True, exist_ok=True)
        weights = root / "model.pt"
        weights.write_bytes(b"pt-artifact")
        output = root / "converted"
        with patch.object(convert_model, "load_ultralytics", return_value=(None, _FakeModel)):
            generated = convert_model.export_model(self._args(weights, output))
        self.assertEqual({path.suffix for path in generated}, {".pt", ".onnx"})
        manifest = convert_model.write_manifest(self._args(weights, output), generated)
        self.assertTrue(manifest.is_file())
        self.assertEqual(manifest.read_text(encoding="utf-8").count('"sha256"'), 3)

    def test_mobile_conversion_reports_windows_limitation(self):
        root = self.TEST_ROOT / "mobile"
        root.mkdir(parents=True, exist_ok=True)
        weights = root / "model.pt"
        weights.write_bytes(b"pt-artifact")
        args = self._args(weights, root / "converted", fmt="mobile", server_format="onnx")
        with patch.object(convert_model, "load_ultralytics", return_value=(None, _FakeModel)), patch(
            "tools.convert_model.platform.system", return_value="Windows"
        ):
            with self.assertRaisesRegex(RuntimeError, "不支持 Windows"):
                convert_model.export_model(args)


if __name__ == "__main__":
    unittest.main()
