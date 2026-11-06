import base64
import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import ValidationError

from app.app_updates import contract
from app.app_updates.signatures import verify_envelope, strict_json

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / "docs/app-update-v1-golden.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 29, 4, 1, tzinfo=timezone.utc)
CONTEXT = {key: GOLDEN["examples"]["checkAvailable"]["value"][key] for key in
           ("publisherId", "packageName", "channel", "deploymentId", "installationId", "requestId", "currentVersionCode")}


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class AppUpdateContractTest(unittest.TestCase):
    def test_schema_export_and_golden_have_one_authority(self):
        self.assertEqual(contract.schema_document(), json.loads((ROOT / "docs/app-update-v1.schema.json").read_text(encoding="utf-8")))
        for name, sample in GOLDEN["examples"].items():
            with self.subTest(name=name):
                model = getattr(contract, sample["type"])
                self.assertEqual(sample["value"], model.model_validate_json(json.dumps(sample["value"])).model_dump(mode="json"))
        self.assertEqual("com.aiyolo.inspection", contract.PACKAGE_NAME)
        self.assertEqual(1, contract.FIRST_VERSION_CODE)

    def test_both_sources_and_recovery_semantics_reject_invalid_values(self):
        cases = [
            ("checkAvailable", {"result": "up_to_date"}),
            ("checkAvailable", {"currentVersionCode": 101}),
            ("checkAvailable", {"currentVersionCode": True}),
            ("checkAvailable", {"policyRevision": 2**63}),
            ("checkAvailable", {"contractVersion": "app-update/v2"}),
            ("checkAvailable", {"unknownRequiredField": True}),
            ("downloadExternal", {"downloadUrl": "http://apk.example.com/101"}),
            ("downloadExternal", {"downloadUrl": "https://user:password@apk.example.com/101"}),
            ("downloadExternal", {"allowedDownloadHosts": ["other.example.com"]}),
            ("downloadExternal", {"accessMode": "presigned"}),
            ("downloadExternal", {"sha256": "A" * 64}),
            ("downloadExternal", {"sizeBytes": 0}),
            ("downloadMinio", {"downloadUrlExpiresAt": None}),
            ("installPermission", {"offlineInstallAllowed": True}),
            ("installPermission", {"userActionRequired": False}),
            ("installPermission", {"authorizationExpiresAt": "2026-10-29T04:03:00Z"}),
            ("healthyReceipt", {"observedVersionCode": 100}),
            ("healthyReceipt", {"stage": "failed"}),
        ]
        for name, changes in cases:
            sample = GOLDEN["examples"][name]
            with self.subTest(name=name, changes=changes), self.assertRaises(ValidationError):
                getattr(contract, sample["type"]).model_validate_json(json.dumps(sample["value"] | changes))
        for modify in (lambda r: r.update(releasePurpose="recovery"),
                       lambda r: r.update(versionCode=1),
                       lambda r: r.update(readableDataSchemaRange={"min": 1, "max": 18})):
            value = copy.deepcopy(GOLDEN["examples"]["checkAvailable"]["value"])
            modify(value["release"])
            with self.assertRaises(ValidationError):
                contract.CheckPayload.model_validate_json(json.dumps(value))

    def test_fixed_golden_signature_uses_exact_bytes_and_context(self):
        vector = GOLDEN["signedVector"]
        public = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(vector["publicKeyBase64Url"] + "="))
        raw = json.dumps(vector["envelope"]).encode()
        args = dict(trusted_keys={"golden-test-key": public}, message_type="check", expected=CONTEXT,
                    min_policy_revision=12, now=NOW)
        self.assertEqual(101, verify_envelope(raw, **args).release.versionCode)
        for changes in ({"min_policy_revision": 13}, {"now": NOW + timedelta(hours=1)},
                        {"now": NOW - timedelta(hours=1)}, {"trusted_keys": {}},
                        {"expected": CONTEXT | {"deploymentId": "other"}},
                        {"expected": {}}, {"message_type": "download"}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, ValidationError)):
                verify_envelope(raw, **(args | changes))
        tampered = vector["envelope"] | {"payloadBase64Url": b64(vector["payloadUtf8"].replace('"versionCode":101', '"versionCode":102').encode())}
        with self.assertRaises(InvalidSignature):
            verify_envelope(json.dumps(tampered).encode(), **args)

    def test_signed_duplicate_utf8_oversize_and_wrong_domain_fail_closed(self):
        private = Ed25519PrivateKey.generate()
        def signed(raw, domain=contract.SIGNATURE_DOMAIN):
            return json.dumps(dict(keyId="test", payloadBase64Url=b64(raw), signatureBase64Url=b64(private.sign(domain + raw)))).encode()
        args = dict(trusted_keys={"test": private.public_key()}, message_type="check", expected=CONTEXT, min_policy_revision=12, now=NOW)
        original = GOLDEN["signedVector"]["payloadUtf8"].encode()
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'\xff', b" " * (contract.MAX_METADATA_BYTES + 1)):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                verify_envelope(signed(raw), **args)
        with self.assertRaises(InvalidSignature):
            verify_envelope(signed(original, b"MODEL-MANIFEST/v1\x00"), **args)
        with self.assertRaises(ValueError):
            strict_json(b'{"nested":{"a":1,"a":2}}')

    def test_download_and_install_signatures_bind_exact_artifact_and_source(self):
        private = Ed25519PrivateKey.generate()
        for name, message_type in (("downloadExternal", "download"), ("downloadMinio", "download"),
                                   ("installPermission", "install_permission")):
            payload = GOLDEN["examples"][name]["value"]
            raw = json.dumps(payload).encode()
            envelope = json.dumps(dict(keyId="test", payloadBase64Url=b64(raw),
                signatureBase64Url=b64(private.sign(contract.SIGNATURE_DOMAIN + raw)))).encode()
            expected = CONTEXT | {key: payload[key] for key in ("releaseId", "artifactId", "sourceId",
                "sourceRevision", "versionCode", "sha256", "sizeBytes", "signerSha256")}
            args = dict(trusted_keys={"test": private.public_key()}, message_type=message_type,
                        expected=expected, min_policy_revision=12, now=NOW)
            with self.subTest(name=name):
                self.assertEqual(payload["sourceId"], verify_envelope(envelope, **args).sourceId)
                for changed in ({"sourceRevision": 999}, {"artifactId": "other"}, {"sha256": "f" * 64}):
                    with self.assertRaises(ValueError):
                        verify_envelope(envelope, **(args | {"expected": expected | changed}))
                with self.assertRaises(ValueError):
                    verify_envelope(envelope, **(args | {"expected": CONTEXT}))

    def test_api_prefix_permissions_errors_and_signed_payloads(self):
        schema = contract.schema_document()
        for api in schema["x-api"]:
            self.assertTrue(api["path"].startswith("/aiyoloapi/"))
            self.assertEqual("PLATFORM_ADMIN" if "/admin/" in api["path"] else "deployment", api["auth"])
        for code, (status, retry) in contract.ERRORS.items():
            contract.ErrorBody(code=code, message=code, requestId="request", retryable=retry)
            with self.assertRaises(ValidationError):
                contract.ErrorBody(code=code, message=code, requestId="request", retryable=not retry)
            self.assertGreaterEqual(status, 400)
