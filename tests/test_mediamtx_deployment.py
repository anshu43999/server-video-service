"""M34-T04: static deployment contracts, no containers or business DB writes."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "deploy/k8s/production"


class MediaRetirementDeploymentTests(unittest.TestCase):
    def test_compose_removes_distribution_without_losing_storage_or_egress(self):
        config = yaml.safe_load((ROOT / "compose.yml").read_text(encoding="utf-8"))
        self.assertEqual({"video-service", "model-converter"}, set(config["services"]))
        self.assertEqual({"model-data", "evidence-data", "calibration-data", "converter-data"}, set(config["volumes"]))
        self.assertTrue(config["networks"]["control"]["internal"])
        self.assertFalse((config["networks"]["media"] or {}).get("internal", False))
        for name, service in config["services"].items():
            self.assertIn("media", service["networks"])
            self.assertTrue(service["read_only"])
            self.assertIn("ALL", service["cap_drop"])
            self.assertFalse(any(key.startswith(("MEDIAMTX_", "MEDIA_", "MTX_")) for key in service["environment"]))
            self.assertNotIn("MAX_OUTPUT_SUBSCRIBERS", service["environment"])
            if name == "video-service":
                self.assertEqual({"model-converter"}, set(service["depends_on"]))
                self.assertEqual(1, len(service["ports"]))
                self.assertTrue(service["ports"][0].endswith(":8080"))
                self.assertIn("RTSP_TRANSPORT", service["environment"])
            else:
                self.assertNotIn("ports", service)

    def test_kubernetes_has_no_media_workload_service_or_env(self):
        kustomization = yaml.safe_load((K8S / "kustomization.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("mediamtx.yaml", kustomization["resources"])
        for name in kustomization["resources"]:
            path = K8S / name
            self.assertTrue(path.is_file(), name)
            self.assertNotIn("mediamtx", path.read_text(encoding="utf-8").lower())
        services = list(yaml.safe_load_all((K8S / "services.yaml").read_text(encoding="utf-8")))
        self.assertEqual({"aiyolo-video-service", "aiyolo-model-converter"}, {s["metadata"]["name"] for s in services})
        self.assertEqual({8080, 8090}, {p["port"] for s in services for p in s["spec"]["ports"]})

    def test_examples_no_longer_require_media_variables(self):
        for name in (".env.example", "deploy/k8s/production/config.env.example", "deploy/k8s/production/secret.env.example"):
            with self.subTest(name=name):
                for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
                    if line.strip() and not line.startswith("#"):
                        key = line.split("=", 1)[0]
                        self.assertFalse(key.startswith(("MEDIAMTX_", "MEDIA_", "SRT_", "DIAGNOSTIC_")), key)
                        self.assertNotEqual("MAX_OUTPUT_SUBSCRIBERS", key)

    def test_old_settings_are_ignored_even_if_enabled_or_malformed(self):
        legacy = {"MEDIAMTX_ENABLED": "true", "MEDIAMTX_INTERNAL_TOKEN": "old-secret",
                  "MEDIAMTX_RTSP_URL": "rtsp://obsolete:8554", "MEDIAMTX_VIDEO_ENCODER": "invalid",
                  "MEDIAMTX_RECONNECT_DELAY": "invalid-number", "MAX_OUTPUT_SUBSCRIBERS": "invalid-number"}
        with patch.dict(os.environ, legacy, clear=True):
            self.assertFalse(any(k.startswith("mediamtx_") or k == "max_output_subscribers" for k in Settings(_env_file=None).model_dump()))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.env"
            path.write_text("\n".join(f"{k}={v}" for k, v in legacy.items()), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings(_env_file=path)
                self.assertNotIn("old-secret", str(settings.model_dump()))
                self.assertEqual("tcp", settings.rtsp_transport)

    def test_local_launcher_has_no_media_process_or_parameters(self):
        script = (ROOT / "start-server.ps1").read_text(encoding="utf-8")
        for retired in ("WithMediaMtx", "MediaPublicHost", "MEDIAMTX_", "Start-Process", "mediaProcess"):
            self.assertNotIn(retired, script)
        self.assertIn("[CmdletBinding()]", script)
        self.assertIn("uvicorn app.main:app", script)
        executable = shutil.which("powershell.exe")
        if executable:
            rejected = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "start-server.ps1"), "-WithMediaMtx"], capture_output=True, timeout=15)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn(b"WithMediaMtx", rejected.stderr)

    def test_deploy_requires_local_acceptance_and_never_prunes_volumes_or_orphans(self):
        script = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")
        self.assertIn("AIYOLO_LOCAL_ACCEPTANCE_RECORD", script)
        self.assertLess(script.index("finish local acceptance first"), script.index("compose build --pull"))
        self.assertNotIn("--remove-orphans", script)
        self.assertNotIn("down -v", script)
        self.assertNotIn("model-converter mediamtx", script)

    def test_deploy_script_parses_without_running_docker(self):
        git_bash = Path("C:/Program Files/Git/bin/bash.exe")
        executable = str(git_bash) if git_bash.is_file() else shutil.which("bash")
        if not executable:
            self.skipTest("Bash is required for shell syntax validation")
        result = subprocess.run([executable, "-n", str(ROOT / "deploy/deploy.sh")], capture_output=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_old_config_is_test_only_and_never_in_container_build(self):
        self.assertFalse((ROOT / "deploy/mediamtx/mediamtx.yml.example").exists())
        self.assertFalse((K8S / "mediamtx.yaml").exists())
        fixture = (ROOT / "tests/fixtures/retired-mediamtx.yml").read_text(encoding="utf-8")
        self.assertIn("negative-test fixture ONLY; never deploy", fixture)
        self.assertIn("authHTTPExclude: []", fixture)
        self.assertIn("tests", (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())


if __name__ == "__main__":
    unittest.main()
