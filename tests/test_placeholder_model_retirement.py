import json
import unittest
from pathlib import Path


class PlaceholderModelRetirementTests(unittest.TestCase):
    def test_site_intrusion_placeholder_is_absent_from_runtime_catalog(self):
        root = Path(__file__).resolve().parents[1]
        registry = json.loads((root / "models" / "registry.json").read_text(encoding="utf-8"))

        self.assertNotIn("site-intrusion-v1", {item.get("modelId") for item in registry["models"]})
        for path in (
            root / "models" / "site-intrusion-v1-manifest.json",
            root / "models" / "placeholders" / "site-intrusion-v1-server.onnx",
            root / "models" / "placeholders" / "site-intrusion-v1-android.tflite",
            root / "models" / "placeholders" / "site-intrusion-v1-labels.txt",
        ):
            self.assertFalse(path.exists(), str(path))


if __name__ == "__main__":
    unittest.main()
