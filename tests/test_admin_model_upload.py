from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminModelUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script_path = ROOT / "app" / "static" / "conversion.js"
        self.script = self.script_path.read_text(encoding="utf-8")
        self.styles = (ROOT / "app" / "static" / "conversion.css").read_text(encoding="utf-8")
        self.index = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")

    def test_selected_pt_file_has_prominent_name_size_and_state(self) -> None:
        for marker in (
            'id="conversion-file-title"',
            'id="conversion-file-meta"',
            "renderSelectedModelFile(file)",
            "formatFileSize(file.size)",
            "drop.classList.toggle('is-selected', selected)",
            ".conversion-drop.is-selected",
        ):
            self.assertTrue(marker in self.script or marker in self.styles, marker)

    def test_success_clears_upload_controls_but_failure_remains_retryable(self) -> None:
        success = "if (xhr.status >= 200 && xhr.status < 300) { resetModelUploadState();"
        self.assertIn(success, self.script)
        self.assertIn("byId('conversion-file').value = '';", self.script)
        self.assertIn("byId('conversion-name').value = '';", self.script)
        self.assertIn("byId('conversion-upload-status').hidden = true", self.script)
        self.assertNotIn("xhr.onerror = () => { resetModelUploadState()", self.script)
        self.assertNotIn("xhr.ontimeout = () => { resetModelUploadState()", self.script)

    def test_conversion_jobs_show_stage_and_real_or_indeterminate_progress(self) -> None:
        for marker in (
            "job.stage_label",
            "job.queue_position",
            "job.progress_message",
            "is-indeterminate",
            "job.progress}%",
            "formatDuration",
        ):
            self.assertIn(marker, self.script)
        self.assertIn("conversion-progress-scan", self.styles)

    def test_static_asset_version_and_javascript_syntax(self) -> None:
        self.assertIn("conversion.css?v=20260921-conversion-progress", self.index)
        self.assertIn("conversion.js?v=20260921-conversion-progress", self.index)
        subprocess.run(["node", "--check", str(self.script_path)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
