import unittest
from pathlib import Path
from app.detector import YoloDetector


class ModelMetadataTests(unittest.TestCase):
    def test_missing_model_metadata_is_traceable(self):
        path = str(Path("models") / "definitely-missing-test-model.pt")
        detector = YoloDetector(path, 0.4, 416, "cpu", ["person", "tool"])
        metadata = detector.metadata()
        self.assertFalse(metadata["model_exists"])
        self.assertEqual(metadata["imgsz"], 416)
        self.assertEqual(metadata["classes"], ["person", "tool"])
        self.assertFalse(metadata["loaded"])


if __name__ == "__main__":
    unittest.main()
