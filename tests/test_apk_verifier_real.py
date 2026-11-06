from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from apk_test_support import ApkFixtures
from app.app_updates.apk_verifier import ApkVerifier, Expectations, VerificationError

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("RUN_APK_TOOL_TESTS") == "1", "requires real Android SDK tools")
class RealApkVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="real-apk-", dir=ROOT / ".tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.fixtures = ApkFixtures(cls.root)
        cls.first = cls.fixtures.apk("first", native_abi="arm64-v8a")
        cls.second = cls.fixtures.apk("second", version=2)
        cls.unsigned = cls.fixtures.apk("unsigned", sign=False)
        cls.wrong = cls.fixtures.apk("wrong", package="com.other.app")
        cls.major = cls.fixtures.apk("major", major=1)
        cls.signer = cls.fixtures.signer(cls.first)
        cls.verifier = ApkVerifier(cls.fixtures.tools)

    def verify(self, apk=None, **kwargs):
        with (apk or self.first).open("rb") as stream:
            return self.verifier.verify(stream, **(dict(approved_signer_sha256=self.signer, high_water=0) | kwargs))

    def rejected(self, apk, code, **kwargs):
        with self.assertRaises(VerificationError) as caught:
            self.verify(apk, **kwargs)
        self.assertEqual(code, caught.exception.code)
        self.assertEqual("failed", json.loads(Path(caught.exception.evidence_ref).read_text())["status"])

    def test_real_tools_verify_metadata_hash_signature_and_next_version(self):
        result = self.verify()
        self.assertEqual(("com.aiyolo.inspection", 1, 27, ("arm64-v8a",)),
            (result.package_name, result.version_code, result.min_sdk, result.abis))
        self.assertEqual(hashlib.sha256(self.first.read_bytes()).hexdigest(), result.sha256)
        self.assertEqual(self.first.stat().st_size, result.size_bytes)
        self.assertEqual(2, self.verify(self.second, high_water=1).version_code)
        report = json.loads(Path(result.evidence_ref).read_text())
        self.assertIn("Android Asset Packaging", report["tools"]["aapt2"]["version"])
        self.assertEqual([], list(self.fixtures.tools.staging_root.iterdir()))

    def test_unsigned_wrong_package_certificate_and_version_rejected(self):
        self.rejected(self.unsigned, "apk_signature_invalid")
        self.rejected(self.wrong, "package_mismatch")
        self.rejected(self.first, "signer_not_approved", approved_signer_sha256="f" * 64)
        self.rejected(self.second, "version_not_increasing")
        self.rejected(self.first, "version_not_increasing", high_water=1)
        self.rejected(self.major, "apk_version_major_unsupported")

    def test_signed_archive_tamper_truncation_html_and_metadata_mismatch(self):
        changed = self.root / "tampered.apk"
        changed.write_bytes(self.first.read_bytes())
        with zipfile.ZipFile(changed, "a") as archive:
            archive.writestr("assets/changed", b"after-signing")
        self.rejected(changed, "apk_signature_invalid")
        truncated = self.root / "truncated.apk"
        truncated.write_bytes(self.first.read_bytes()[:-30])
        self.rejected(truncated, "apk_invalid_zip")
        html = self.root / "html.apk"
        html.write_bytes(b"<html>download</html>")
        self.rejected(html, "apk_invalid_zip")
        self.rejected(self.first, "size_mismatch", expected=Expectations(size_bytes=1))
        self.rejected(self.first, "hash_mismatch", expected=Expectations(sha256="a" * 64))

    def test_existing_product_debug_certificate_is_rejected(self):
        product = os.environ.get("APK_TEST_PRODUCT_DEBUG")
        if not product:
            self.skipTest("no existing product APK supplied")
        product = Path(product)
        signer = self.fixtures.signer(product)
        self.rejected(product, "debug_signer_forbidden", approved_signer_sha256=signer)
