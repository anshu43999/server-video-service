import unittest
from app.alerts.engine import run_vector


class AlertOperatorSmokeTests(unittest.TestCase):
    def test_all_operator_vectors_are_executable(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        seen = set()
        for path in (root / "docs/alert-engine-conformance").glob("*.json"):
            vector = json.loads(path.read_text(encoding="utf-8"))
            result = run_vector(vector)
            self.assertIsInstance(result["events"], list)
            seen.update(r["operator"] for r in vector["rules"] if r["operator"] not in {"METRIC_THRESHOLD", "RELATION", "COMPOSITE"})
        self.assertEqual(seen, {"PRESENCE", "IN_REGION", "LINE_CROSS", "DWELL", "COUNT", "AREA_RATIO", "RATE", "ABSENCE"})


if __name__ == "__main__":
    unittest.main()
