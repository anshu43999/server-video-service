import io
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app.app_updates.apk_verifier import ApkVerifier, Expectations, Toolchain, VerificationError

ROOT = Path(__file__).resolve().parents[1]


def fake_apk():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
        archive.writestr("classes.dex", b"dex\n035\0")
    return stream.getvalue()


class ApkVerifierTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="apk-unit-", dir=ROOT / ".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tools = Toolchain(self.root / "aapt2", self.root / "java", self.root / "signer.jar",
                               self.root / "evidence", self.root / "staging")
        for name in ("aapt2", "java", "signer.jar"):
            (self.root / name).write_bytes(b"unit-tool")
        self.verifier = ApkVerifier(self.tools)
        self.signer = "b" * 64

    def outputs(self, label, command, run, **kwargs):
        if label in ("badging", "manifest", "apksigner"):
            self.assertTrue(Path(command[-1]).is_absolute())
        if label == "java-version":
            (run / "java-version.stderr").write_text('openjdk version "21"', encoding="utf-8")
        return {"badging": "package: name='com.aiyolo.inspection' versionCode='1' versionName='0.1.0'\nminSdkVersion:'27'\n",
                "manifest": "E: manifest\n", "apksigner": "Verifies\nNumber of signers: 1\nSigner #1 certificate SHA-256 digest: " + self.signer + "\nVerified using v2 scheme (APK Signature Scheme v2): true\n"}.get(label, "test-version")

    def verify(self, data=None, **kwargs):
        return self.verifier.verify(io.BytesIO(fake_apk() if data is None else data),
            **(dict(approved_signer_sha256=self.signer, high_water=0) | kwargs))

    def fails(self, code, **kwargs):
        with self.assertRaises(VerificationError) as caught:
            self.verify(**kwargs)
        self.assertEqual(code, caught.exception.code)
        report = json.loads(Path(caught.exception.evidence_ref).read_text(encoding="utf-8"))
        self.assertEqual("failed", report["status"])
        self.assertEqual(code, report["errorCode"])
        if self.tools.staging_root.exists():
            self.assertEqual([], list(self.tools.staging_root.iterdir()))

    def test_stream_hash_size_tool_identity_and_snapshot_cleanup(self):
        with patch.object(self.verifier, "_run", side_effect=self.outputs):
            result = self.verify()
        self.assertEqual(1, result.version_code)
        self.assertEqual(len(fake_apk()), result.size_bytes)
        self.assertEqual(4, len(result.abis))  # no native code is ABI-independent
        self.assertTrue(Path(result.evidence_ref).is_file())
        self.assertEqual([], list(self.tools.staging_root.iterdir()))
        report = json.loads(Path(result.evidence_ref).read_text())
        self.assertIn("version", report["tools"]["aapt2"])

    def test_relative_staging_configuration_passes_absolute_snapshot_to_tools(self):
        import os
        relative = Path(os.path.relpath(self.tools.staging_root, Path.cwd()))
        self.verifier = ApkVerifier(replace(self.tools, staging_root=relative))
        with patch.object(self.verifier, "_run", side_effect=self.outputs):
            self.assertEqual(1, self.verify().version_code)

    def test_missing_signer_or_tool_fails_closed(self):
        self.fails("signer_not_configured", approved_signer_sha256=None)
        (self.root / "aapt2").unlink()
        self.fails("tool_missing")

    def test_bad_file_size_hash_and_declared_identity(self):
        with patch.object(self.verifier, "_run", side_effect=self.outputs):
            self.fails("apk_invalid_zip", data=b"<html>login</html>")
            self.fails("apk_invalid_zip", data=fake_apk()[:-20])
            self.fails("apk_empty", data=b"")
            self.fails("size_mismatch", expected=Expectations(size_bytes=999))
            self.fails("hash_mismatch", expected=Expectations(sha256="a" * 64))
            self.fails("version_mismatch", expected=Expectations(version_code=2))
            self.fails("signer_not_approved", expected=Expectations(signer_sha256="f" * 64))
            self.fails("version_not_increasing", high_water=1)
        self.verifier = ApkVerifier(replace(self.tools, max_bytes=10))
        with patch.object(self.verifier, "_run", side_effect=self.outputs):
            self.fails("apk_too_large")

    def test_split_code_major_bad_sdk_and_abi(self):
        badging = "package: name='com.aiyolo.inspection' versionCode='1' versionName='0.1'\nminSdkVersion:'27'\n"
        for text, tree, abis in ((badging, "A: split=\"config.arm64\"", set()),
            (badging, "A: android:versionCodeMajor(0x01010576)=1", set()),
            (badging.replace("'27'", "'26'"), "", set()),
            (badging + "maxSdkVersion:'30'\n", "", set()),
            (badging, "", {"arm64-v8a"}),
            (badging.replace("versionCode='1'", "versionCode='2147483648'"), "", set())):
            with self.subTest(tree=tree, text=text), self.assertRaises(VerificationError):
                self.verifier._parse_manifest(text, tree, abis)

    def test_zip_duplicate_traversal_and_expansion_limit(self):
        for extra in ("../bad", "AndroidManifest.xml", "lib/riscv64/evil.so"):
            stream = io.BytesIO(fake_apk())
            with zipfile.ZipFile(stream, "a") as archive:
                archive.writestr(extra, b"bad")
            with patch.object(self.verifier, "_run", side_effect=self.outputs), self.assertRaises(VerificationError):
                self.verify(data=stream.getvalue())
        self.verifier = ApkVerifier(replace(self.tools, max_expanded_bytes=2))
        with patch.object(self.verifier, "_run", side_effect=self.outputs):
            self.fails("apk_expansion_limit")

    def test_tool_failure_timeout_and_output_limit_are_recorded(self):
        # Exercise the actual subprocess boundary with a harmless Python child.
        import sys
        run = self.root / "process"
        run.mkdir()
        for label, source, expected in (("exit", "raise SystemExit(3)", "tool_failed"),
            ("timeout", "import time;time.sleep(5)", "tool_timeout"),
            ("output", "print('x'*10000)", "tool_output_limit")):
            # Only the sleeping child exercises a short deadline. Interpreter
            # startup under concurrent SDK/browser load must not mask exit/output.
            verifier = ApkVerifier(replace(self.tools, timeout_seconds=0.3 if label=="timeout" else 5,
                                          output_limit_bytes=500))
            with self.assertRaises(VerificationError) as caught:
                verifier._run(label, [sys.executable, "-c", source], run)
            self.assertEqual(expected, caught.exception.code)
            self.assertTrue((run / (label + ".result.json")).exists())

    def test_v1_multiple_signers_unknown_certificate_and_tool_error_fail_closed(self):
        outputs = self.outputs
        for replacement, expected in (("Number of signers: 2\n", "multiple_or_missing_signers"),
            ("Verifies\nNumber of signers: 1\nSigner #1 certificate SHA-256 digest: " + self.signer + "\n", "apk_v2_signature_required")):
            def fake(label, command, run, **kwargs):
                return replacement if label == "apksigner" else outputs(label, command, run, **kwargs)
            with patch.object(self.verifier, "_run", side_effect=fake):
                self.fails(expected)
        def failed(label, command, run, **kwargs):
            if label == "apksigner":
                raise VerificationError("apk_signature_invalid")
            return outputs(label, command, run, **kwargs)
        with patch.object(self.verifier, "_run", side_effect=failed):
            self.fails("apk_signature_invalid")
