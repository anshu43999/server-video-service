"""Old publishing benchmarks must fail, never report fake capacity."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CapacityRetirementTests(unittest.TestCase):
    def test_publisher_benchmark_runtime_is_removed(self):
        self.assertIsNone(importlib.util.find_spec("app.capacity"))

    def test_old_publish_and_dry_run_invocations_fail_explicitly(self):
        for mode in ("--publish", "--dry-run", "--help"):
            with self.subTest(mode=mode):
                result = subprocess.run([sys.executable, str(ROOT / "tools/capacity_benchmark.py"), mode], capture_output=True, text=True, timeout=10)
                self.assertEqual(2, result.returncode)
                payload = json.loads(result.stdout)
                self.assertEqual("retired", payload["status"])
                self.assertNotIn("effective_fps", payload)


if __name__ == "__main__":
    unittest.main()
