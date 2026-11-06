import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.model_catalog import ModelCatalog


def _artifact(path: Path, artifact_id: str) -> dict:
    return {
        "artifactId": artifact_id,
        "format": "pt",
        "platform": "server",
        "path": f"models/{path.parent.name}/{path.name}",
        "sizeBytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    }


def _release(model_id: str, version: str, path: Path, *, status: str = "PUBLISHED") -> dict:
    return {
        "modelId": model_id,
        "name": f"{model_id} {version}",
        "version": version,
        "scenario": "intrusion",
        "purpose": "business",
        "runtime": "server-pt",
        "format": "pt",
        "path": f"models/{path.parent.name}/{path.name}",
        "sizeBytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "labels": ["person"],
        "releaseEligible": status == "PUBLISHED",
        "status": status,
        "artifacts": [_artifact(path, "server-pt")],
    }


class ModelVersionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        models = root / "models"
        (models / "v1").mkdir(parents=True)
        (models / "v2").mkdir(parents=True)
        self.v1 = models / "v1" / "model.pt"
        self.v2 = models / "v2" / "model.pt"
        self.v1.write_bytes(b"version-one")
        self.v2.write_bytes(b"version-two")
        self.registry = models / "registry.json"
        self.registry.write_text(json.dumps({
            "activeServerModel": "vision",
            "models": [
                _release("vision", "1.0.0", self.v1),
                _release("vision", "2.0.0", self.v2),
            ],
        }), encoding="utf-8")
        self.catalog = ModelCatalog(self.registry)

    def tearDown(self):
        self.temp.cleanup()

    def test_multiple_versions_choose_highest_published_and_expose_history(self):
        versions = self.catalog.versions("vision")
        self.assertEqual([item["version"] for item in versions], ["2.0.0", "1.0.0"])
        self.assertEqual(self.catalog.get("vision")["version"], "2.0.0")
        self.assertEqual(self.catalog.get("vision")["latestVersion"], "2.0.0")
        self.assertTrue(self.catalog.get("vision", "2.0.0")["isLatest"])

    def test_version_level_uninstall_keeps_other_release_and_writes_tombstone(self):
        result = self.catalog.uninstall("vision", "1.0.0")
        self.assertEqual(result["version"], "1.0.0")
        self.assertFalse(self.v1.exists())
        self.assertTrue(self.v2.exists())
        payload = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual([item["version"] for item in payload["models"]], ["2.0.0"])
        self.assertEqual(payload["modelHistory"][-1]["status"], "UNINSTALLED")

    def test_legacy_uninstall_requires_version_for_multiple_releases(self):
        with self.assertRaisesRegex(ValueError, "version required"):
            self.catalog.uninstall("vision")

    def test_active_release_is_protected_but_deprecation_is_audited(self):
        with self.assertRaisesRegex(ValueError, "active model release"):
            self.catalog.uninstall("vision", "2.0.0")
        result = self.catalog.set_release_status("vision", "2.0.0", "DEPRECATED", "newer release")
        self.assertEqual(result["status"], "DEPRECATED")
        self.assertEqual(result["latestVersion"], "1.0.0")
        payload = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(payload["modelHistory"][-1]["status"], "DEPRECATED")

    def test_duplicate_release_is_rejected_by_startup_validation(self):
        payload = json.loads(self.registry.read_text(encoding="utf-8"))
        payload["models"].append(dict(payload["models"][0]))
        self.registry.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate release"):
            self.catalog.validate_startup()

    def test_binding_rejects_retired_releases_even_when_no_published_version_remains(self):
        for status in ("DEPRECATED", "REVOKED", "UNINSTALLED"):
            with self.subTest(status=status):
                payload = json.loads(self.registry.read_text())
                for item in payload["models"]:
                    item["status"] = status
                    item["serverReady"] = True
                self.registry.write_text(json.dumps(payload))
                for version in (None, "1.0.0", "2.0.0"):
                    with self.assertRaisesRegex(ValueError, status.lower()):
                        self.catalog.resolve_server_model("vision", version)
                self.assertFalse(any(m["serverReady"] or m["serverBindable"] for m in self.catalog.list_models()))

    def test_binding_projection_selects_only_the_resolved_version(self):
        rows = self.catalog.list_models()
        self.assertTrue(all(m["serverReady"] for m in rows))
        self.assertEqual([m["version"] for m in rows if m["serverBindable"]], ["2.0.0"])

    def test_stale_ready_flags_cannot_override_missing_or_corrupt_files(self):
        payload = json.loads(self.registry.read_text())
        for item in payload["models"]:
            item["serverReady"] = True
        self.registry.write_text(json.dumps(payload))
        self.v1.unlink()
        self.v2.write_bytes(b"tampered")
        self.assertFalse(any(m["serverReady"] or m["serverBindable"] for m in self.catalog.list_models()))

    def test_missing_hash_is_not_bindable(self):
        payload = json.loads(self.registry.read_text())
        payload["models"][1]["sha256"] = ""
        self.registry.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.catalog.resolve_server_model("vision")
        self.assertFalse(self.catalog.get("vision")["serverReady"])

    def test_declared_size_mismatch_disables_readiness(self):
        payload = json.loads(self.registry.read_text())
        payload["models"][1]["sizeBytes"] += 1
        self.registry.write_text(json.dumps(payload))
        self.assertFalse(self.catalog.get("vision")["serverReady"])
        with self.assertRaisesRegex(ValueError, "size"):
            self.catalog.resolve_server_model("vision")

    def test_unsigned_android_artifact_stays_converted_but_not_installable(self):
        mobile = self.v2.parent / "model.tflite"
        mobile.write_bytes(b"mobile")
        artifact = _artifact(mobile, "android-int8")
        artifact.update(format="tflite", platform="android")
        payload = json.loads(self.registry.read_text())
        release = payload["models"][1]
        release.update(androidReady=True, androidConverted=True, signatureStatus="unsigned")
        release["artifacts"].append(artifact)
        self.registry.write_text(json.dumps(payload))
        result = self.catalog.get("vision")
        self.assertTrue(result["androidConverted"])
        self.assertFalse(result["androidReady"])
        self.assertTrue(result["serverBindable"])

    def test_android_integrity_failure_does_not_disable_valid_server_artifact(self):
        mobile = self.v2.parent / "model.tflite"
        mobile.write_bytes(b"mobile")
        artifact = _artifact(mobile, "android-int8")
        artifact.update(format="tflite", platform="android")
        payload = json.loads(self.registry.read_text())
        release = payload["models"][1]
        release.update(androidReady=True, androidConverted=True, signatureStatus="signed")
        release["artifacts"].append(artifact)
        self.registry.write_text(json.dumps(payload))
        self.assertTrue(self.catalog.get("vision")["androidReady"])
        mobile.write_bytes(b"broken")
        result = self.catalog.get("vision")
        self.assertFalse(result["androidReady"])
        self.assertFalse(result["androidConverted"])
        self.assertTrue(result["serverReady"])
        self.assertTrue(result["serverBindable"])

    def test_target_capabilities_are_independent_and_legacy_is_derived(self):
        mobile = self.v2.parent / "model.tflite"
        mobile.write_bytes(b"mobile")
        artifact = _artifact(mobile, "android-int8")
        artifact.update(format="tflite", platform="android")
        payload = json.loads(self.registry.read_text())
        release = payload["models"][1]
        release.update(androidReady=True, androidConverted=True, signatureStatus="signed",
                       supportedTargets=["pc", "mobile"])
        release["artifacts"].append(artifact)
        self.registry.write_text(json.dumps(payload), encoding="utf-8")

        result = self.catalog.get("vision")
        self.assertEqual(["pc", "mobile"], result["supportedTargets"])
        self.assertTrue(result["targetReadiness"]["pc"]["ready"])
        self.assertTrue(result["targetReadiness"]["mobile"]["ready"])

        # An absent legacy declaration is projected from verified artifacts,
        # not from a stale conversion flag.
        payload["models"][1].pop("supportedTargets")
        payload["models"][1]["androidReady"] = False
        self.registry.write_text(json.dumps(payload), encoding="utf-8")
        legacy = self.catalog.get("vision")
        self.assertEqual(["pc"], legacy["supportedTargets"])
        self.assertFalse(legacy["targetReadiness"]["mobile"]["ready"])

    def test_mobile_only_declaration_blocks_pc_readiness_activation_and_runtime(self):
        payload = self.catalog._load()
        payload["models"][1]["supportedTargets"] = ["mobile"]
        self.catalog._save(payload)
        row = self.catalog.get("vision")
        self.assertFalse(row["serverReady"])
        self.assertFalse(row["serverBindable"])
        self.assertFalse(self.catalog.is_published_release("vision", "2.0.0"))
        for operation in (self.catalog.activate, self.catalog.resolve_server_model):
            with self.assertRaisesRegex(ValueError, "support pc"):
                operation("vision", "2.0.0")

    def test_invalid_explicit_targets_fail_closed_and_startup_rejects_them(self):
        for targets in ([], None, "pc", ["pc", "pc"], ["invalid"], [{}]):
            with self.subTest(targets=targets):
                payload = self.catalog._load()
                payload["models"][1]["supportedTargets"] = targets
                self.catalog._save(payload)
                row = self.catalog.get("vision")
                self.assertEqual([], row["supportedTargets"])
                self.assertFalse(row["serverReady"])
                with self.assertRaisesRegex(ValueError, "supportedTargets"):
                    self.catalog.validate_startup()
                with self.assertRaisesRegex(ValueError, "supportedTargets"):
                    self.catalog.resolve_server_model("vision")

    def test_pc_publication_does_not_require_mobile_conversion(self):
        payload = self.catalog._load()
        release = payload["models"][1]
        release.update(status="READY", releaseEligible=False, supportedTargets=["pc", "mobile"],
                       serverValidated=True, serverValidationSha256=release["sha256"], sourceSha256=release["sha256"])
        self.catalog._save(payload)
        row = self.catalog.publish_release("vision", "2.0.0", ["pc"],
            license_approved=True, reason="license reviewed", actor="admin")
        self.assertEqual("PUBLISHED", row["status"])
        self.assertTrue(row["targetReleaseEligible"]["pc"])
        self.assertFalse(row["targetReleaseEligible"]["mobile"])
        self.assertFalse(row["androidReady"])
        with self.assertRaisesRegex(ValueError, "model_target_not_ready"):
            self.catalog.publish_release("vision", "2.0.0", ["mobile"],
                license_approved=True, reason="mobile review", actor="admin")
        self.assertEqual(["pc"], self.catalog._load()["models"][1]["publishedTargets"])

    def test_publication_rejects_unreviewed_license_and_unvalidated_runtime(self):
        payload = self.catalog._load()
        payload["models"][1].update(status="READY", releaseEligible=False, sourceSha256="a" * 64)
        self.catalog._save(payload)
        for approved, expected in ((False, "license approval"), (True, "runtime validation")):
            with self.assertRaisesRegex(ValueError, expected):
                self.catalog.publish_release("vision", "2.0.0", ["pc"],
                    license_approved=approved, reason="review", actor="admin")
        self.assertEqual("READY", self.catalog.get("vision", "2.0.0")["status"])

    def test_pc_validation_is_recorded_against_current_artifact_hash(self):
        payload = self.catalog._load()
        payload["models"][1].update(status="READY", releaseEligible=False, sourceSha256="a" * 64,
                                    supportedTargets=["pc"])
        self.catalog._save(payload)
        with self.assertRaisesRegex(ValueError, "PC runtime validation"):
            self.catalog.publish_release("vision", "2.0.0", ["pc"],
                license_approved=True, reason="review", actor="admin")
        validated = self.catalog.record_pc_runtime_validation("vision", "2.0.0",
            {"ok": True, "warmup": "passed", "ultralytics": "test-runtime"})
        self.assertTrue(validated["serverValidated"])
        self.assertEqual(validated["sha256"], validated["serverValidationSha256"])
        published = self.catalog.publish_release("vision", "2.0.0", ["pc"],
            license_approved=True, reason="review", actor="admin")
        self.assertEqual("PUBLISHED", published["status"])

    def test_pc_validation_rejects_failed_runtime_and_stale_artifact(self):
        payload = self.catalog._load()
        payload["models"][1].update(status="READY", supportedTargets=["pc"])
        self.catalog._save(payload)
        with self.assertRaisesRegex(ValueError, "did not pass"):
            self.catalog.record_pc_runtime_validation("vision", "2.0.0", {"ok": False})
        self.catalog.record_pc_runtime_validation("vision", "2.0.0", {"ok": True, "warmup": "passed"})
        self.v2.write_bytes(b"modified after validation")
        with self.assertRaisesRegex(ValueError, "model_target_not_ready"):
            self.catalog.publish_release("vision", "2.0.0", ["pc"],
                license_approved=True, reason="review", actor="admin")

    def test_explicit_migration_moves_one_release_and_keeps_audit_history(self):
        migrated = self.catalog.migrate_release("vision", "helmet-family", "1.0.0", "confirmed upgrade", "operator-1")
        self.assertEqual("helmet-family", migrated["modelId"])
        self.assertEqual("vision", migrated["migratedFromModelId"])
        self.assertEqual({"1.0.0"}, {item["version"] for item in self.catalog.versions("helmet-family")})
        self.assertEqual({"2.0.0"}, {item["version"] for item in self.catalog.versions("vision")})
        history = json.loads(self.registry.read_text(encoding="utf-8"))["modelHistory"]
        self.assertEqual("MIGRATED", history[-1]["status"])
        self.assertEqual("operator-1", history[-1]["actor"])

    def test_explicit_migration_rejects_existing_target_release(self):
        self.catalog.migrate_release("vision", "helmet-family", "1.0.0")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.catalog.migrate_release("vision", "helmet-family", "1.0.0")
        # The failed request must not mutate the remaining source release.
        self.assertEqual("vision", self.catalog.get("vision", "2.0.0")["modelId"])


if __name__ == "__main__":
    unittest.main()
