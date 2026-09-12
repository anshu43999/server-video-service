import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
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
        app.include_router(create_conversion_router(self.service, self.catalog, max_upload_bytes=128, signer=self.signer))
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

    def upload(self, payload=b"custom-weights", filename="best.pt"):
        return self.client.post("/api/conversion/uploads", params={"filename": filename, "name": "安全帽", "version": "2.0"},
                                content=payload, headers=self.headers)

    def wait(self, job):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.service.get(job["id"])
            if job["status"] not in {"queued", "running"}:
                return job
            time.sleep(0.01)
        self.fail("job did not finish")

    def test_upload_requires_admin_and_rejects_empty_wrong_format_and_size(self):
        self.assertEqual(self.client.get("/api/conversion/config").status_code, 401)
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
        response = self.client.post(f'/api/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers)
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
        self.assertEqual(self.client.post(f'/api/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers).status_code, 409)

    def test_mobile_failure_preserves_server_and_retry_recovers(self):
        upload = self.upload().json()
        self.wait(upload["job"])
        self.service.runner.fail_mobile = True
        job = self.client.post(f'/api/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers).json()
        self.assertEqual(self.wait(job)["status"], "failed")
        self.assertTrue(self.catalog.get(upload["model_id"])["serverReady"])
        self.assertFalse(self.catalog.get(upload["model_id"])["androidReady"])
        self.service.runner.fail_mobile = False
        response = self.client.post(f'/api/conversion/jobs/{job["id"]}/retry', headers=self.headers)
        self.assertEqual(self.wait(response.json())["status"], "succeeded")

    def test_invalid_pt_is_never_published_and_missing_config_does_not_block_pt(self):
        (self.service.root / "config.json").unlink()
        upload = self.upload(b"broken").json()
        self.assertEqual(self.wait(upload["job"])["status"], "failed")
        self.assertEqual(self.catalog.list_models(), [])
        good = self.upload().json()
        self.assertEqual(self.wait(good["job"])["status"], "succeeded")
        self.assertEqual(self.client.post(f'/api/conversion/uploads/{good["upload_id"]}/mobile', headers=self.headers).status_code, 409)

    def test_config_and_environment_check_are_async_admin_operations(self):
        response = self.client.put("/api/conversion/config", json={"mode": "local", "python_path": sys.executable, "auto_convert": True}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        job = self.client.post("/api/conversion/check", headers=self.headers).json()
        self.assertTrue(self.wait(job)["result"]["mobile_available"])
        upload = self.upload().json()
        self.wait(upload["job"])
        mobile = next(job for job in self.service.jobs() if job["action"] == "mobile")
        self.assertEqual(self.wait(mobile)["status"], "succeeded")

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
        job = self.client.post(f'/api/conversion/uploads/{uploaded["upload_id"]}/mobile', headers=self.headers).json()
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
            signer=ModelManifestSigner(None, None),
        ))
        self.client.close()
        self.client = TestClient(app)
        self.service.start()
        upload = self.upload().json()
        self.wait(upload["job"])
        mobile = self.client.post(f'/api/conversion/uploads/{upload["upload_id"]}/mobile', headers=self.headers).json()
        self.assertEqual(self.wait(mobile)["status"], "succeeded")
        model = self.catalog.get(upload["model_id"])
        self.assertTrue(model["androidConverted"])
        self.assertFalse(model["androidReady"])
        self.assertEqual(model["signatureStatus"], "unsigned")


if __name__ == "__main__":
    unittest.main()
