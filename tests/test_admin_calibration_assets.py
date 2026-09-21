from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminCalibrationAssetsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script_path = ROOT / "app" / "static" / "conversion.js"
        self.script = self.script_path.read_text(encoding="utf-8")
        self.styles = (ROOT / "app" / "static" / "conversion.css").read_text(encoding="utf-8")
        self.index = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")

    def test_admin_supports_real_calibration_assets_and_task_selection(self) -> None:
        for value in (
            "/api/conversion/calibration-datasets",
            "calibration-upload-form",
            "conversion-calibration-select",
            "calibrationDatasetId",
            "default_calibration_dataset_id",
        ):
            self.assertIn(value, self.script)
        self.assertNotIn('id="conversion-calibration"', self.script)
        self.assertIn(".calibration-layout", self.styles)
        self.assertIn(".calibration-row", self.styles)

    def test_calibration_management_is_a_separate_model_workspace(self) -> None:
        for value in (
            'id="model-tab-calibration"',
            'id="model-pane-calibration"',
            'id="model-calibration-workspace"',
        ):
            self.assertIn(value, self.index)
        self.assertIn("calibrationWorkspace.append(calibrationPanel)", self.script)
        self.assertIn("workspace.append(panel)", self.script)
        self.assertIn('id="conversion-calibration-select"', self.script)
        self.assertNotIn("INT8 校准数据 YAML", self.script)

    def test_script_has_valid_javascript_syntax(self) -> None:
        subprocess.run(["node", "--check", str(self.script_path)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
