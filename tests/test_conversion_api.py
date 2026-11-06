import hashlib
import io
import json
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.calibration import CalibrationDatasetCatalog
from app.conversion import ConversionConfig, ConversionService, ProcessRunner
from app.conversion_api import create_conversion_router
from app.model_catalog import ModelCatalog
from app.model_signing import ModelManifestSigner, canonical_manifest_payload


class FakeRunner(ProcessRunner):
    fail_mobile = False

    def run(self, config, action, directory, stopping):
        if action == "check":
            return {"ok": True, "server_available": True, "mobile_available": True}
        directory.mkdir(parents=True, exist_ok=True)
        if (directory / "source.pt").read_bytes() == b"broken":
            raise ValueError("invalid PT")
        result = {"ok": True, "labels": ["helmet", "person"], "input_size": config.input_size,
                  "ultralytics": "test", "warmup": "passed"}
        if action == "mobile":
            if self.fail_mobile:
                raise RuntimeError("export unavailable")
            payload = b"verified-by-fake-runtime"
            (directory / "android.tflite").write_bytes(payload)
            result.update(
                sha256=hashlib.sha256(payload).hexdigest(),
                sizeBytes=len(payload),
                quantization="int8",
                input={
                    "name": "serving_default_args_0",
                    "shape": [1, 3, 640, 640],
                    "dataType": "float32",
                    "quantization": [0.0, 0],
                },
                output={
                    "name": "serving_default_output_0_output_dequant",
                    "shape": [1, 6, 8400],
                    "dataType": "float32",
                    "quantization": [0.0, 0],
                },
            )
        return result


class ConversionApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "models").mkdir()
        (root / "models" / "registry.json").write_text(json.dumps({"models": []}), encoding="utf-8")
        self.catalog = ModelCatalog(root / "models" / "registry.json")
        self.service = ConversionService(root / "models" / "local-conversion", FakeRunner())
        self.calibration_catalog = CalibrationDatasetCatalog(
            root / "calibration", max_expanded_bytes=1024 * 1024, max_files=10
        )
        self.service.configure(ConversionConfig(mode="local", python_path=sys.executable))
        self.private_key = Ed25519PrivateKey.generate()
        self.private_key_path = root / "test-signing-key.pem"
        self.private_key_path.write_bytes(self.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        app = FastAPI()
        self.signer = ModelManifestSigner("test-2026", self.private_key_path)
        app.include_router(create_conversion_router(
            self.service, self.catalog, max_upload_bytes=128,
            calibration_catalog=self.calibration_catalog,
            max_calibration_upload_bytes=4096, signer=self.signer,
        ))
        self.client = TestClient(app)
        self.old_token = settings.admin_token
        settings.admin_token = "test-only"
        self.headers = {"X-Admin-Token": "test-only"}
        self.service.start()

    def tearDown(self):
        self.service.close()
        self.client.close()
        settings.admin_token = self.old_token
        self.tmp.cleanup()

    def upload(self, payload=b"custom-weights", filename="best.pt", model_id=None, version="2.0", targets=None):
        params = {"filename": filename, "name": "安全帽", "version": version}
        if model_id is not None:
            params["modelId"] = model_id
        if targets is not None:
            params["supportedTargets"] = targets
        return self.client.post("/aiyoloapi/conversion/uploads", params=params,
                                content=payload, headers=self.headers)

    def test_stable_model_id_is_reused_for_new_versions_without_hash_or_name_auto_merge(self):
        first = self.upload(model_id="helmet-family", version="1.0.0").json()
        self.assertEqual("helmet-family", first["model_id"])
        self.assertEqual("succeeded", self.wait(first["job"])["status"])
        second = self.upload(payload=b"new-version", model_id="helmet-family", version="2.0.0").json()
        self.assertEqual("helmet-family", second["model_id"])
        self.assertEqual("succeeded", self.wait(second["job"])["status"])
        self.assertEqual({"1.0.0", "2.0.0"}, {item["version"] for item in self.catalog.versions("helmet-family")})

        # A missing modelId remains an isolated upload family, even when its
        # name and source bytes happen to match an existing release.
        isolated = self.upload(version="3.0.0").json()
        self.assertEqual("succeeded", self.wait(isolated["job"])["status"])
        self.assertTrue(isolated["model_id"].startswith("uploaded-"))
        self.assertEqual(2, len(self.catalog.versions("helmet-family")))
        self.assertEqual("3.0.0", self.catalog.get(isolated["model_id"])["version"])

    @staticmethod
    def calibration_zip(*, unsafe_name: str | None = None) -> bytes:
        output = io.BytesIO()
        # Valid 1x1 RGB PNG.
        png = __import__("base64").b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr(unsafe_name or "camera/frame-001.png", png)
        return output.getvalue()

    def wait(self, job):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.service.get(job["id"])
            if job["status"] not in {"queued", "running"}:
                return job
            time.sleep(0.01)
        self.fail("job did not finish")

    def test_upload_requires_admin_and_rejects_empty_wrong_format_and_size(self):
        self.assertEqual(self.client.get("/aiyoloapi/conversion/config").status_code, 401)
        self.assertEqual(self.upload(b"").status_code, 422)
        self.assertEqual(self.upload(filename="best.onnx").status_code, 422)
        self.assertEqual(self.upload(b"x" * 129).status_code, 413)
        self.assertEqual(list((self.service.root / "uploads").iterdir()), [])

    def test_pt_ready_then_mobile_publish_uses_same_identity_and_real_hashes(self):
        upload = self.upload().json()
        self.assertEqual(self.wait(upload["job"])["status"], "succeeded")
        model = self.catalog.get(upload["model_id"])
        self.assertEqual(model["labels"], ["helmet", "person"])
        self.assertEqual(model["version"], "2.0")
        self.assertTrue(model["serverReady"])
        self.assertFalse(model["androidReady"])
        response = self.client.post(f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.wait(response.json())["status"], "succeeded")
        model = self.catalog.get(upload["model_id"])
        self.assertTrue(model["androidReady"])
        self.assertTrue(model["androidConverted"])
        self.assertEqual(model["signatureStatus"], "signed")
        self.assertEqual(len(self.catalog.list_models()), 1)
        self.assertEqual({a["artifactId"] for a in model["artifacts"]}, {"server-pt", "android-int8", "android-manifest"})
        self.catalog.validate_startup()
        _, artifact = self.catalog.get_artifact(upload["model_id"], "android-int8")
        self.assertEqual(artifact.read_bytes(), b"verified-by-fake-runtime")
        _, manifest_path = self.catalog.get_artifact(upload["model_id"], "android-manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["signature"]["keyId"], "test-2026")
        payload = canonical_manifest_payload(manifest)
        self.private_key.public_key().verify(
            __import__("base64").b64decode(manifest["signature"]["signatureBase64"]), payload,
        )
        self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest["signature"]["signedPayloadSha256"])
        self.assertEqual(self.client.post(f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers).status_code, 409)

    def test_business_mobile_release_signs_immutable_manifest_and_retries_preserve_bytes(self):
        upload = self.upload(targets=["mobile"]).json()
        self.assertEqual("succeeded", self.wait(upload["job"])["status"])
        response = self.client.post(f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers)
        self.assertEqual("succeeded", self.wait(response.json())["status"])
        model_id = upload["model_id"]
        _, original_path = self.catalog.get_artifact(model_id, "android-manifest")
        original_bytes = original_path.read_bytes()
        before = self.catalog.registry_path.read_bytes()
        args = dict(license_approved=True, reason="approved internal distribution", actor="admin", signer=self.signer)
        with patch.object(self.signer, "sign", side_effect=ValueError("signing failed")):
            with self.assertRaisesRegex(ValueError, "signing failed"):
                self.catalog.publish_release(model_id, "2.0", ["mobile"], **args)
        self.assertEqual(before, self.catalog.registry_path.read_bytes())
        self.assertEqual(original_bytes, original_path.read_bytes())
        result = self.catalog.publish_release(model_id, "2.0", ["mobile"], **args)
        self.assertTrue(result["targetReleaseEligible"]["mobile"])
        self.assertFalse(result["targetReleaseEligible"]["pc"])
        _, release_path = self.catalog.get_artifact(model_id, "android-manifest")
        release_bytes = release_path.read_bytes()
        manifest = json.loads(release_bytes)
        self.assertNotIn("purpose", manifest)
        legacy_manifest = {**manifest, "purpose": "development"}
        self.assertIn(b"purpose=development", canonical_manifest_payload(legacy_manifest))
        self.assertNotEqual(original_path, release_path)
        self.assertTrue(manifest["releaseEligible"])
        self.assertEqual("approved", manifest["license"]["distribution"])
        self.private_key.public_key().verify(__import__("base64").b64decode(manifest["signature"]["signatureBase64"]),
                                             canonical_manifest_payload(manifest))
        _, tflite = self.catalog.get_artifact(model_id, "android-int8")
        self.assertEqual(hashlib.sha256(tflite.read_bytes()).hexdigest(), manifest["modelFile"]["sha256"])
        with patch.object(self.signer, "sign", side_effect=ValueError("must not resign")):
            self.catalog.publish_release(model_id, "2.0", ["mobile"], **args)
        self.assertEqual(release_bytes, release_path.read_bytes())
        self.assertEqual(original_bytes, original_path.read_bytes())
        self.catalog.validate_startup()

    def test_dual_release_can_convert_and_publish_mobile_after_pc_publication(self):
        upload = self.upload(targets=["pc", "mobile"]).json()
        self.assertEqual("succeeded", self.wait(upload["job"])["status"])
        args = dict(license_approved=True, reason="reviewed", actor="admin", signer=self.signer)
        self.catalog.publish_release(upload["model_id"], "2.0", ["pc"], **args)
        response = self.client.post(f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers)
        self.assertEqual("succeeded", self.wait(response.json())["status"])
        pc = self.catalog.get(upload["model_id"])
        self.assertTrue(pc["targetReleaseEligible"]["pc"])
        self.assertFalse(pc["targetReleaseEligible"]["mobile"])
        result = self.catalog.publish_release(upload["model_id"], "2.0", ["mobile"], **args)
        self.assertEqual({"pc": True, "mobile": True}, result["targetReleaseEligible"])

    def test_mobile_release_refuses_missing_signer_and_mismatched_verified_contract(self):
        upload = self.upload(targets=["mobile"]).json()
        self.assertEqual("succeeded", self.wait(upload["job"])["status"])
        response = self.client.post(f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers)
        self.assertEqual("succeeded", self.wait(response.json())["status"])
        args = dict(license_approved=True, reason="reviewed", actor="admin")
        with self.assertRaisesRegex(ValueError, "signer is required"):
            self.catalog.publish_release(upload["model_id"], "2.0", ["mobile"], **args)
        registry = self.catalog._load()
        registry["models"][0]["androidContract"]["input_size"] = 999
        self.catalog._save(registry)
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.catalog.publish_release(upload["model_id"], "2.0", ["mobile"], signer=self.signer, **args)
        self.assertEqual("READY", self.catalog.get(upload["model_id"])["status"])

    def test_explicit_pc_only_upload_skips_auto_conversion_and_rejects_mobile(self):
        self.service.configure(ConversionConfig(mode="local", python_path=sys.executable, auto_convert=True))
        upload = self.upload(targets=["pc"]).json()
        self.assertEqual("succeeded", self.wait(upload["job"])["status"])
        model = self.catalog.get(upload["model_id"])
        self.assertEqual(["pc"], model["supportedTargets"])
        self.assertTrue(model["serverReady"])
        self.assertFalse(any(job["action"] == "mobile" for job in self.service.jobs()))
        response = self.client.post(f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers)
        self.assertEqual(409, response.status_code)
        self.assertEqual("model_target_not_supported", response.json()["detail"]["code"])

    def test_mobile_only_upload_keeps_source_pt_separate_from_pc_capability(self):
        upload = self.upload(targets=["mobile"]).json()
        self.assertEqual("succeeded", self.wait(upload["job"])["status"])
        model = self.catalog.get(upload["model_id"])
        self.assertFalse(model["serverReady"])
        self.assertFalse(model["androidReady"])
        job = self.client.post(f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers)
        self.assertEqual(202, job.status_code, job.text)
        self.assertEqual("succeeded", self.wait(job.json())["status"])
        model = self.catalog.get(upload["model_id"])
        self.assertEqual(["mobile"], model["supportedTargets"])
        self.assertTrue(model["androidReady"])
        self.assertFalse(model["serverBindable"])
        with self.assertRaisesRegex(ValueError, "support pc"):
            self.catalog.resolve_server_model(upload["model_id"])

    def test_mobile_conversion_uses_upload_version_instead_of_latest_family(self):
        first = self.upload(model_id="family", version="1.0.0").json()
        self.assertEqual("succeeded", self.wait(first["job"])["status"])
        second = self.upload(model_id="family", version="2.0.0").json()
        self.assertEqual("succeeded", self.wait(second["job"])["status"])
        job = self.client.post(f'/aiyoloapi/conversion/uploads/{first["upload_id"]}/mobile', headers=self.headers)
        self.assertEqual(202, job.status_code, job.text)
        self.assertEqual("succeeded", self.wait(job.json())["status"])
        self.assertTrue(self.catalog.get("family", "1.0.0")["androidReady"])
        self.assertFalse(self.catalog.get("family", "2.0.0")["androidReady"])

    def test_calibration_asset_is_versioned_selected_and_reference_protected(self):
        datasets = self.client.get("/aiyoloapi/conversion/calibration-datasets", headers=self.headers).json()["datasets"]
        self.assertEqual(["coco8-dev"], [item["datasetId"] for item in datasets])
        created = self.client.post(
            "/aiyoloapi/conversion/calibration-datasets",
            params={"filename": "site.zip", "name": "工地巡检", "version": "1.0", "scenario": "construction"},
            content=self.calibration_zip(), headers={**self.headers, "Content-Type": "application/zip"},
        )
        self.assertEqual(201, created.status_code, created.text)
        dataset = created.json()
        self.assertEqual(1, dataset["imageCount"])
        self.assertEqual(64, len(dataset["contentSha256"]))
        self.assertTrue((self.calibration_catalog.root / dataset["yamlPath"]).is_file())

        upload = self.upload().json()
        self.wait(upload["job"])
        mobile = self.client.post(
            f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile',
            params={"calibrationDatasetId": dataset["datasetId"]}, headers=self.headers,
        ).json()
        completed = self.wait(mobile)
        self.assertEqual("succeeded", completed["status"])
        self.assertEqual(dataset["contentSha256"], completed["result"]["calibration_dataset"]["contentSha256"])
        model = self.catalog.get(upload["model_id"])
        self.assertIn("calibrationDataset", model, model)
        self.assertEqual(dataset["datasetId"], model["calibrationDataset"]["datasetId"])
        blocked = self.client.delete(
            f'/aiyoloapi/conversion/calibration-datasets/{dataset["datasetId"]}', headers=self.headers
        )
        self.assertEqual(409, blocked.status_code)

        image = next((self.calibration_catalog.root / dataset["yamlPath"]).parent.joinpath("images").iterdir())
        image.write_bytes(b"changed-after-registration")
        inspected = self.client.get(
            f'/aiyoloapi/conversion/calibration-datasets/{dataset["datasetId"]}', headers=self.headers
        )
        self.assertEqual(200, inspected.status_code)
        self.assertEqual("invalid", inspected.json()["status"])

    def test_unreferenced_calibration_asset_can_be_deleted(self):
        created = self.client.post(
            "/aiyoloapi/conversion/calibration-datasets",
            params={"filename": "temporary.zip", "name": "临时校准集", "version": "1", "scenario": "test"},
            content=self.calibration_zip(), headers={**self.headers, "Content-Type": "application/zip"},
        )
        self.assertEqual(201, created.status_code, created.text)
        dataset = created.json()
        directory = (self.calibration_catalog.root / dataset["yamlPath"]).parent
        self.assertTrue(directory.is_dir())
        deleted = self.client.delete(
            f'/aiyoloapi/conversion/calibration-datasets/{dataset["datasetId"]}', headers=self.headers
        )
        self.assertEqual(200, deleted.status_code, deleted.text)
        self.assertFalse(directory.exists())
        self.assertEqual(404, self.client.get(
            f'/aiyoloapi/conversion/calibration-datasets/{dataset["datasetId"]}', headers=self.headers
        ).status_code)

    def test_calibration_upload_rejects_path_traversal(self):
        response = self.client.post(
            "/aiyoloapi/conversion/calibration-datasets",
            params={"filename": "bad.zip", "name": "bad", "version": "1", "scenario": "test"},
            content=self.calibration_zip(unsafe_name="../escape.png"),
            headers={**self.headers, "Content-Type": "application/zip"},
        )
        self.assertEqual(422, response.status_code)
        self.assertFalse((self.calibration_catalog.root.parent / "escape.png").exists())

    def test_mobile_failure_preserves_server_and_retry_recovers(self):
        upload = self.upload().json()
        self.wait(upload["job"])
        self.service.runner.fail_mobile = True
        job = self.client.post(f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers).json()
        self.assertEqual(self.wait(job)["status"], "failed")
        self.assertTrue(self.catalog.get(upload["model_id"])["serverReady"])
        self.assertFalse(self.catalog.get(upload["model_id"])["androidReady"])
        self.service.runner.fail_mobile = False
        response = self.client.post(f'/aiyoloapi/conversion/jobs/{job["id"]}/retry', headers=self.headers)
        self.assertEqual(self.wait(response.json())["status"], "succeeded")

    def test_invalid_pt_is_never_published_and_missing_config_does_not_block_pt(self):
        (self.service.root / "config.json").unlink()
        upload = self.upload(b"broken").json()
        self.assertEqual(self.wait(upload["job"])["status"], "failed")
        self.assertEqual(self.catalog.list_models(), [])
        good = self.upload().json()
        self.assertEqual(self.wait(good["job"])["status"], "succeeded")
        self.assertEqual(self.client.post(f'/aiyoloapi/conversion/uploads/{good["upload_id"]}/mobile', headers=self.headers).status_code, 409)

    def test_signing_status_exposes_rotation_state_without_secret_path(self):
        signer = ModelManifestSigner(
            "new-2026", self.private_key_path,
            trusted_key_ids="old-2025,new-2026",
            revoked_key_ids="old-2024",
        )
        app = FastAPI()
        app.include_router(create_conversion_router(
            self.service, self.catalog, calibration_catalog=self.calibration_catalog, signer=signer,
        ))
        with TestClient(app) as client:
            response = client.get("/aiyoloapi/conversion/signing-status", headers=self.headers)
        self.assertEqual(200, response.status_code)
        status = response.json()
        self.assertTrue(status["configured"])
        self.assertTrue(status["rotationWindowActive"])
        self.assertEqual(
            "sha256:" + hashlib.sha256(self.private_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw,
            )).hexdigest(),
            status["publicKeyFingerprint"],
        )
        self.assertEqual(["new-2026", "old-2025"], status["trustedKeyIds"])
        self.assertEqual(["old-2024"], status["revokedKeyIds"])
        self.assertNotIn("privateKeyPath", status)
        self.assertNotIn(str(self.private_key_path), str(status))

    def test_revoked_active_key_cannot_sign(self):
        signer = ModelManifestSigner(
            "old-2025", self.private_key_path,
            trusted_key_ids="old-2025,new-2026",
            revoked_key_ids="old-2025",
        )
        self.assertFalse(signer.configured)
        with self.assertRaisesRegex(ValueError, "未配置|撤销"):
            signer.sign({"schemaVersion": 1})

    def test_config_and_environment_check_are_async_admin_operations(self):
        response = self.client.put("/aiyoloapi/conversion/config", json={"mode": "local", "python_path": sys.executable, "auto_convert": True}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        job = self.client.post("/aiyoloapi/conversion/check", headers=self.headers).json()
        self.assertTrue(self.wait(job)["result"]["mobile_available"])
        upload = self.upload().json()
        self.wait(upload["job"])
        mobile = next(job for job in self.service.jobs() if job["action"] == "mobile")
        self.assertEqual(self.wait(mobile)["status"], "succeeded")

    def test_jobs_expose_stage_activity_and_terminal_progress(self):
        upload = self.upload().json()
        queued = self.client.get("/aiyoloapi/conversion/jobs", headers=self.headers).json()["jobs"]
        current = next(job for job in queued if job["id"] == upload["job"]["id"])
        self.assertIn(current["stage"], {"queued", "starting", "preparing", "loading_model", "validating_model", "completed"})
        self.assertIn("activity_at", current)
        completed = self.wait(upload["job"])
        self.assertEqual("succeeded", completed["status"])
        self.assertEqual("completed", completed["stage"])
        self.assertEqual(100, completed["progress"])
        self.assertIsNotNone(completed["started_at"])
        self.assertIsNotNone(completed["completed_at"])

    def test_changed_upload_and_placeholder_are_rejected(self):
        uploaded = self.upload().json()
        self.wait(uploaded["job"])
        registry = self.catalog._load()
        registry["models"][0]["placeholder"] = True
        self.catalog._save(registry)
        with self.assertRaisesRegex(ValueError, "placeholder"):
            self.catalog.activate(uploaded["model_id"])
        with self.assertRaisesRegex(ValueError, "placeholder"):
            self.catalog.resolve_server_model(uploaded["model_id"])
        registry["models"][0]["placeholder"] = False
        self.catalog._save(registry)
        (self.service.root / "uploads" / uploaded["upload_id"] / "source.pt").write_bytes(b"changed")
        job = self.client.post(f'/aiyoloapi/conversion/uploads/{uploaded["upload_id"]}/mobile', headers=self.headers).json()
        self.assertEqual(self.wait(job)["status"], "failed")
        self.assertFalse(self.catalog.get(uploaded["model_id"])["androidReady"])

    def test_missing_signer_keeps_converted_artifact_uninstallable(self):
        self.service.close()
        root = Path(self.tmp.name)
        self.service = ConversionService(root / "models" / "unsigned-conversion", FakeRunner())
        self.service.configure(ConversionConfig(mode="local", python_path=sys.executable))
        app = FastAPI()
        app.include_router(create_conversion_router(
            self.service, self.catalog, max_upload_bytes=128,
            calibration_catalog=self.calibration_catalog,
            max_calibration_upload_bytes=4096,
            signer=ModelManifestSigner(None, None),
        ))
        self.client.close()
        self.client = TestClient(app)
        self.service.start()
        upload = self.upload().json()
        self.wait(upload["job"])
        mobile = self.client.post(f'/aiyoloapi/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers).json()
        self.assertEqual(self.wait(mobile)["status"], "succeeded")
        model = self.catalog.get(upload["model_id"])
        self.assertTrue(model["androidConverted"])
        self.assertFalse(model["androidReady"])
        self.assertFalse(model["releaseEligible"])
        self.assertEqual("READY", model["status"])
        self.assertEqual(model["signatureStatus"], "unsigned")


if __name__ == "__main__":
    unittest.main()
