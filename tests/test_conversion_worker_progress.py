import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.conversion_worker import write_progress


class ConversionWorkerProgressTests(unittest.TestCase):
    def test_progress_replace_retries_transient_windows_access_denied(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original_replace = Path.replace
            attempts = 0

            def transient_access_denied(source, target):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError(5, "Access is denied")
                return original_replace(source, target)

            with patch.object(Path, "replace", autospec=True, side_effect=transient_access_denied), \
                    patch("tools.conversion_worker.time.sleep"):
                write_progress(directory, "exporting", "正在导出", 42)

            payload = json.loads((directory / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "exporting")
            self.assertEqual(payload["progress"], 42)
            self.assertEqual(attempts, 3)
            self.assertEqual(list(directory.glob("progress.json.*.tmp")), [])

    def test_progress_replace_preserves_error_after_retry_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch("tools.conversion_worker.Path.replace", side_effect=PermissionError(5, "Access is denied")), \
                    patch("tools.conversion_worker.time.sleep"):
                with self.assertRaises(PermissionError):
                    write_progress(directory, "exporting", "正在导出", 42)

            self.assertEqual(list(directory.glob("progress.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
