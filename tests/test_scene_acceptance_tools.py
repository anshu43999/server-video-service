import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import accept_scene_execution_service as acceptance
import refresh_local_scene_service as refresh
from app.model_signing import build_android_manifest, canonical_manifest_payload


class AcceptanceToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        key = Ed25519PrivateKey.generate()
        public = root / "public.pem"
        public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        self.key_patch = patch.object(acceptance, "PUBLIC_KEY", public)
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        weights = b"unit-fixture-not-a-runtime-model"
        digest = hashlib.sha256(weights).hexdigest()
        tensor = dict(name="test", shape=[1, 3, 32, 32], dataType="float32", quantization=[0.0, 0])
        manifest = build_android_manifest("test", dict(version="2.0.0", source_sha256="a" * 64), dict(
            labels=["head"], input_size=32, input=tensor, output=tensor, sizeBytes=len(weights), sha256=digest))
        payload = canonical_manifest_payload(manifest)
        manifest["signature"] = dict(algorithm="Ed25519", keyId="internal-dev-2026-01",
            signatureBase64=base64.b64encode(key.sign(payload)).decode(), signedPayloadSha256=hashlib.sha256(payload).hexdigest())
        self.weights, self.manifest = weights, manifest
        self.origin = "/aiyoloapi/models/test/versions/2.0.0/artifacts/"
        self.service = acceptance.Acceptance(root)
        self.service.client.close()
        self.visited = []
        def respond(request):
            self.visited.append(request.url.path)
            if request.url.path == self.origin + "android-int8/download":
                return httpx.Response(200, content=self.weights)
            if request.url.path == self.origin + "android-manifest/download":
                return httpx.Response(200, json=self.manifest)
            return httpx.Response(404)
        self.service.client = httpx.Client(base_url="http://127.0.0.1:8080", transport=httpx.MockTransport(respond))
        self.addCleanup(self.service.close)

    def model(self):
        manifest_bytes = json.dumps(self.manifest, separators=(",", ":"), ensure_ascii=False).encode()
        return dict(modelId="test", version="2.0.0", artifacts=[dict(
            artifactId=identity, target="mobile", url="/aiyoloapi/models/test/artifacts/" + identity + "/download",
            versionedUrl=self.origin + identity + "/download", sizeBytes=len(content), sha256=hashlib.sha256(content).hexdigest().upper())
            for identity, content in (("android-int8", self.weights), ("android-manifest", manifest_bytes))])

    def test_real_crypto_case_insensitive_hashes_and_versioned_urls(self):
        result = self.service.verify_package(self.model())
        self.assertTrue(result["signatureVerified"])
        self.assertTrue(all("/versions/2.0.0/" in path for path in self.visited))

    def test_corrupt_bytes_are_rejected(self):
        model = self.model()
        self.weights = b"bad"
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            self.service.verify_package(model)

    def test_real_invalid_signature_is_rejected_even_when_download_hash_matches(self):
        self.manifest["signature"]["signatureBase64"] = base64.b64encode(b"x" * 64).decode()
        with self.assertRaises(InvalidSignature):
            self.service.verify_package(self.model())

    def test_foreign_url_never_receives_credentials(self):
        self.service.tokens["admin"] = "test-only-token"
        with self.assertRaisesRegex(RuntimeError, "only local"):
            self.service.request("admin", "GET", "https://example.invalid/aiyoloapi/models")
        self.service.tokens.clear()
        self.assertEqual([], self.visited)

    def test_maintenance_requires_two_exact_distinct_process_ids(self):
        with patch.object(sys, "argv", ["refresh", "--expected-listener", "12", "--expected-parent", "12"]):
            with self.assertRaisesRegex(RuntimeError, "distinct"):
                refresh.main()

    def test_maintenance_preflight_does_not_stop_service(self):
        with patch.object(refresh.maintenance, "run") as run:
            refresh.verify_identity(12, 13)
        command = run.call_args.args[0][-1]
        self.assertNotIn("Stop-Process", command)
        self.assertIn("LocalAddress -ne '127.0.0.1'", command)
        self.assertIn("OwningProcess -ne 12", command)


if __name__ == "__main__":
    unittest.main()
