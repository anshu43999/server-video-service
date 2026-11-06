import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModelConversionRegressionTests(unittest.TestCase):
    def test_converted_manifest_is_traceable(self):
        manifest_path = ROOT / "models" / "converted" / "yolo11n_640_manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["sourceWeights"]["sha256"], "0EBBC80D4A7680D14987A577CD21342B65ECFD94632BD9A8DA63AE6417644EE1")
        self.assertEqual(manifest["conversion"]["imgsz"], 640)
        self.assertIn("toolchain", manifest)
        self.assertTrue(manifest["artifacts"])
        self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["artifacts"]))

if __name__ == "__main__":
    unittest.main()
