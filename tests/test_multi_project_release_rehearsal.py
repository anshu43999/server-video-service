import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import rehearse_multi_project_release as rehearsal


class MultiProjectReleaseRehearsalTests(unittest.TestCase):
    def test_pg_ctl_does_not_capture_background_server_pipes(self):
        with patch.object(rehearsal.subprocess, "run") as run:
            rehearsal._run(Path("D:/PostgreSQL/bin/pg_ctl.exe"), "status")
            options = run.call_args.kwargs
            self.assertEqual(subprocess.DEVNULL, options["stdout"])
            self.assertEqual(subprocess.DEVNULL, options["stderr"])
            self.assertEqual(subprocess.DEVNULL, options["stdin"])

    def test_foreground_backup_tools_capture_errors_without_interactive_input(self):
        with patch.object(rehearsal.subprocess, "run") as run:
            rehearsal._run(Path("D:/PostgreSQL/bin/pg_restore.exe"), "--version")
            options = run.call_args.kwargs
            self.assertEqual(subprocess.PIPE, options["stdout"])
            self.assertEqual(subprocess.PIPE, options["stderr"])
            self.assertEqual(subprocess.DEVNULL, options["stdin"])

    def test_old_backup_format_never_starts_a_cluster(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with patch.object(rehearsal.migration, "verify_bundle", return_value={"dialect": "postgresql", "format": 1}), \
                 patch.object(rehearsal.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "format-2"):
                    rehearsal.rehearse(Path(directory), Path("D:/PostgreSQL/bin"))
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
