from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.check_app_update_runtime import check
from tools.install_android_verifier import SHA256, SIZE, install

ROOT = Path(__file__).resolve().parents[1]


class AppUpdateContainerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m42-t14-test-", dir=ROOT / ".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.env = {"APP_UPDATES_ENABLED": "true", "APP_APK_EXTERNAL_ENABLED": "true",
                    "APP_APK_WORKER_ENABLED": "false", "APP_UPDATE_KEY_ID": "test-only-not-production"}
        for name in ("APP_APK_AAPT2_PATH", "APP_APK_JAVA_PATH", "APP_APK_APKSIGNER_JAR_PATH"):
            path = self.root / name
            path.write_bytes(b"synthetic test tool; never executed")
            path.chmod(0o755)
            self.env[name] = str(path)
        for name in ("APP_APK_EVIDENCE_ROOT", "APP_APK_STAGING_ROOT", "APP_APK_EXTERNAL_ROOT"):
            path = self.root / name
            path.mkdir()
            self.env[name] = str(path)
        self.write_json("APP_UPDATE_SCOPES_PATH", [{"contractVersion": "app-update/v1",
            "publisherId": "test", "packageName": "com.aiyolo.inspection",
            "channel": "test", "deploymentId": "test"}])
        self.compatibility = {"server_contract_min": 1, "server_contract_max": 1,
            "data_schema_version": 1, "readable_schema_min": 1, "readable_schema_max": 1,
            "evidence_ref": "synthetic-test-only-not-release-evidence"}
        self.write_json("APP_APK_COMPATIBILITY_PATH", self.compatibility)
        for name in ("APP_UPDATE_PRIVATE_KEY_PATH", "MODEL_SIGNING_PRIVATE_KEY_PATH"):
            path = self.root / name
            path.write_bytes(Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            self.env[name] = str(path)
        self.calls = []

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        self.env[name] = str(path)

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    def result(self):
        return check(self.env, run=self.runner)

    def failed(self, result):
        return {v["check"] for v in result["checks"] if not v["ok"]}

    def test_valid_offline_config_does_not_claim_production_ready(self):
        result = self.result()
        self.assertTrue(result["ok"])
        self.assertFalse(result["production_ready"])
        self.assertIn("client_trust", result["not_checked"])
        self.assertEqual(3, len(self.calls))
        for _, kwargs in self.calls:
            self.assertEqual(subprocess.DEVNULL, kwargs["stdout"])
            self.assertEqual(subprocess.DEVNULL, kwargs["stderr"])
            self.assertEqual(20, kwargs["timeout"])

    def test_both_mandatory_flags_are_checked(self):
        for name in ("APP_UPDATES_ENABLED", "APP_APK_EXTERNAL_ENABLED"):
            with self.subTest(name=name):
                self.env[name] = "false"
                self.assertIn(name, self.failed(self.result()))
                self.env[name] = "true"

    def test_tools_only_does_not_require_signing_or_business_configuration(self):
        env = {k: v for k, v in self.env.items() if k in ("APP_APK_AAPT2_PATH", "APP_APK_JAVA_PATH", "APP_APK_APKSIGNER_JAR_PATH")}
        result = check(env, tools_only=True, run=self.runner)
        self.assertTrue(result["ok"])
        self.assertEqual(3, len(result["checks"]))

    def test_missing_tools_fail(self):
        del self.env["APP_APK_AAPT2_PATH"]
        self.assertIn("aapt2_executable", self.failed(self.result()))

    def test_tool_failure_and_timeout_are_redacted(self):
        for response in (lambda *a, **k: SimpleNamespace(returncode=1),
                         lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("SENSITIVE", 20))):
            result = check(self.env, run=response)
            self.assertFalse(result["ok"])
            self.assertNotIn("SENSITIVE", json.dumps(result))

    def test_empty_wrong_package_and_extra_scope_fields_fail(self):
        for value in ([], [{"packageName": "invalid"}], [{"extra": "value"}]):
            self.write_json("APP_UPDATE_SCOPES_PATH", value)
            self.assertIn("scope_file_schema", self.failed(self.result()))

    def test_compatibility_rejects_boolean_integer_and_invalid_ranges(self):
        for change in ({"data_schema_version": True}, {"server_contract_max": 0},
                       {"readable_schema_min": 2}, {"evidence_ref": ""}):
            self.write_json("APP_APK_COMPATIBILITY_PATH", {**self.compatibility, **change})
            self.assertIn("compatibility_file_schema_only", self.failed(self.result()))

    def test_reused_signing_key_is_rejected(self):
        self.env["MODEL_SIGNING_PRIVATE_KEY_PATH"] = self.env["APP_UPDATE_PRIVATE_KEY_PATH"]
        self.assertIn("app_signing_key_and_configured_model_key_separation", self.failed(self.result()))

    def test_invalid_signing_key_and_key_id_are_rejected(self):
        Path(self.env["APP_UPDATE_PRIVATE_KEY_PATH"]).write_text("not a private key", encoding="utf-8")
        self.env["APP_UPDATE_KEY_ID"] = ""
        self.assertIn("app_signing_key_and_configured_model_key_separation", self.failed(self.result()))

    def test_paths_and_values_never_appear_in_report(self):
        self.env["DATABASE_URL"] = "SENSITIVE-URL-NOT-USED"
        raw = json.dumps(self.result())
        self.assertNotIn(str(self.root), raw)
        self.assertNotIn("SENSITIVE", raw)
        self.assertNotIn("test-only-not-production", raw)

    def test_missing_directory_is_not_created(self):
        path = self.root / "must-not-create"
        self.env["APP_APK_EXTERNAL_ROOT"] = str(path)
        self.assertIn("APP_APK_EXTERNAL_ROOT_permission_estimate", self.failed(self.result()))
        self.assertFalse(path.exists())

    def test_direct_upload_checks_its_own_directory(self):
        self.env["APP_APK_WORKER_ENABLED"] = "true"
        self.assertIn("APP_APK_UPLOAD_ROOT_permission_estimate", self.failed(self.result()))

    def test_archive_wrong_size_and_checksum_fail_before_extracting(self):
        archive = self.root / "wrong.zip"
        archive.write_bytes(b"invalid")
        destination = self.root / "never-created"
        with self.assertRaisesRegex(ValueError, "size_mismatch"):
            install(archive, destination)
        with patch("tools.install_android_verifier.SIZE", archive.stat().st_size):
            with self.assertRaisesRegex(ValueError, "sha256_mismatch"):
                install(archive, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(64, len(SHA256))
        self.assertEqual(63737259, SIZE)

    def test_both_build_paths_include_tools_and_nonroot_smoke(self):
        for name in ("Dockerfile", "Dockerfile.app-updates"):
            value = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("openjdk-17-jre-headless", value)
            self.assertIn("/opt/android/build-tools/36.0.0", value)
            self.assertIn("USER app\nRUN python /app/tools/check_app_update_runtime.py --tools-only", value)
            self.assertNotIn("PRIVATE KEY", value)
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("!tools/install_android_verifier.py", dockerignore)
        self.assertIn("!tools/check_app_update_runtime.py", dockerignore)

    def test_review_fragment_enables_required_flow_and_preserves_secret_boundary(self):
        directory = ROOT / "deploy/k8s/app-updates"
        fragment = yaml.safe_load((directory / "pod-template.fragment.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("kind", fragment)
        self.assertNotIn("apiVersion", fragment)
        container = fragment["containers"][0]
        env = {item["name"]: item for item in container["env"]}
        self.assertEqual("true", env["APP_UPDATES_ENABLED"]["value"])
        self.assertEqual("true", env["APP_APK_EXTERNAL_ENABLED"]["value"])
        self.assertIn("CHANGE_ME", container["name"])
        volumes = {item["name"]: item for item in fragment["volumes"]}
        self.assertFalse(volumes["app-update-signing"]["secret"]["optional"])
        self.assertEqual(0o440, volumes["app-update-signing"]["secret"]["defaultMode"])
        self.assertIn("persistentVolumeClaim", volumes["app-update-evidence"])
        self.assertIn("persistentVolumeClaim", volumes["app-update-data"])
        self.assertEqual(container["image"], fragment["initContainers"][0]["image"])
        self.assertNotIn("app-updates", (ROOT / "deploy/k8s/production/kustomization.yaml").read_text(encoding="utf-8"))

    def test_review_configuration_has_required_flags_without_private_material(self):
        raw = (ROOT / "deploy/k8s/app-updates/config.env.example").read_text(encoding="utf-8")
        self.assertIn("APP_UPDATES_ENABLED=true", raw)
        self.assertIn("APP_APK_EXTERNAL_ENABLED=true", raw)
        self.assertIn("CHANGE_ME_EXISTING_APPROVED_APP_METADATA_KEY_ID", raw)
        self.assertNotIn("BEGIN PRIVATE KEY", raw)


if __name__ == "__main__":
    unittest.main()
