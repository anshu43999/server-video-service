"""Bounded, fail-closed verification shared by upload and external-source jobs.

Inputs are byte streams, never a URL or administrator-selected command. Only
operator-configured SDK tools execute. The verified local snapshot is deleted
on return; callers retain the original immutable staging object for promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import BinaryIO
import zipfile
import zlib

from .contract import MAX_VERSION_CODE, PACKAGE_NAME

ABIS = ("arm64-v8a", "armeabi-v7a", "x86", "x86_64")
HEX = re.compile(r"[0-9a-f]{64}\Z")


class VerificationError(Exception):
    """A stable internal code, without source URL, credentials or tool output."""
    def __init__(self, code: str, evidence_ref: str | None = None):
        super().__init__(code)
        self.code = code
        self.evidence_ref = evidence_ref


@dataclass(frozen=True)
class Toolchain:
    aapt2: Path
    java: Path
    apksigner_jar: Path
    evidence_root: Path
    staging_root: Path
    max_bytes: int = 8 * 1024**3
    max_expanded_bytes: int = 16 * 1024**3
    max_entries: int = 100000
    timeout_seconds: float = 60
    stream_timeout_seconds: float = 300
    output_limit_bytes: int = 1024 * 1024

    @classmethod
    def from_settings(cls, settings):
        if not all((settings.app_apk_aapt2_path, settings.app_apk_java_path, settings.app_apk_apksigner_jar_path)):
            raise VerificationError("tool_missing")
        return cls(Path(settings.app_apk_aapt2_path), Path(settings.app_apk_java_path),
                   Path(settings.app_apk_apksigner_jar_path), Path(settings.app_apk_evidence_root),
                   Path(settings.app_apk_staging_root), max_bytes=settings.app_apk_max_bytes,
                   timeout_seconds=settings.app_apk_tool_timeout_seconds)


@dataclass(frozen=True)
class Expectations:
    package_name: str = PACKAGE_NAME
    version_code: int | None = None
    version_name: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    signer_sha256: str | None = None


@dataclass(frozen=True)
class VerifiedApk:
    package_name: str
    version_code: int
    version_name: str
    min_sdk: int
    abis: tuple[str, ...]
    size_bytes: int
    sha256: str
    signer_sha256: str
    evidence_ref: str


class ApkVerifier:
    def __init__(self, tools: Toolchain):
        self.tools = tools
        if (not 0 < tools.max_bytes <= 8 * 1024**3 or tools.max_entries < 1
                or tools.max_expanded_bytes < 1 or tools.output_limit_bytes < 1
                or not 0 < tools.timeout_seconds <= 300 or not 0 < tools.stream_timeout_seconds <= 1200):
            raise ValueError("invalid verifier limits")

    def verify(self, stream: BinaryIO, *, approved_signer_sha256: str | None,
               high_water: int, expected: Expectations | None = None,
               enforce_first_version: bool = True) -> VerifiedApk:
        expected = expected or Expectations()
        self.tools.evidence_root.mkdir(parents=True, exist_ok=True)
        # Each run has immutable evidence; input names/URLs never become paths.
        run = Path(tempfile.mkdtemp(prefix="apk-", dir=self.tools.evidence_root)).resolve()
        report = dict(startedAt=datetime.now(timezone.utc).isoformat(), status="verifying", tools={})
        try:
            if (not isinstance(approved_signer_sha256, str) or not HEX.fullmatch(approved_signer_sha256)):
                raise VerificationError("signer_not_configured")
            if type(high_water) is not int or not 0 <= high_water <= MAX_VERSION_CODE:
                raise VerificationError("invalid_version_high_water")
            if expected.package_name != PACKAGE_NAME:
                raise VerificationError("package_mismatch")
            self._check_tools(report)
            aapt_version = self._run("aapt2-version", [str(self.tools.aapt2), "version"], run).strip()
            report["tools"]["aapt2"]["version"] = aapt_version or (run / "aapt2-version.stderr").read_text(encoding="utf-8").strip()
            report["tools"]["apksignerJar"]["version"] = self._run("apksigner-version", [str(self.tools.java), "-jar", str(self.tools.apksigner_jar), "version"], run).strip()
            self._run("java-version", [str(self.tools.java), "-version"], run)
            report["tools"]["java"]["version"] = (run / "java-version.stderr").read_text(encoding="utf-8").strip()
            self.tools.staging_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="apk-", dir=self.tools.staging_root.resolve()) as work:
                snapshot = Path(work) / "input.apk"
                size, digest = self._copy(stream, snapshot)
                report.update(sizeBytes=size, sha256=digest)
                if expected.size_bytes is not None and size != expected.size_bytes:
                    raise VerificationError("size_mismatch")
                if expected.sha256 is not None and digest != expected.sha256:
                    raise VerificationError("hash_mismatch")
                zip_abis, has_dex = self._validate_zip(snapshot)
                badging = self._run("badging", [str(self.tools.aapt2), "dump", "badging", str(snapshot)], run)
                tree = self._run("manifest", [str(self.tools.aapt2), "dump", "xmltree", "--file", "AndroidManifest.xml", str(snapshot)], run)
                package, version, name, sdk, abis = self._parse_manifest(badging, tree, zip_abis)
                if not has_dex and not re.search(r":hasCode(?:\(0x[0-9a-f]+\))?=false", tree):
                    raise VerificationError("apk_not_standalone")
                report.update(packageName=package, versionCode=version, versionName=name, minSdk=sdk, abis=abis)
                if package != expected.package_name:
                    raise VerificationError("package_mismatch")
                if ((expected.version_code is not None and version != expected.version_code)
                        or (expected.version_name is not None and name != expected.version_name)):
                    raise VerificationError("version_mismatch")
                if (enforce_first_version and high_water == 0 and version != 1) or version <= high_water:
                    raise VerificationError("version_not_increasing")
                signed = self._run("apksigner", [str(self.tools.java), "-jar", str(self.tools.apksigner_jar),
                    "verify", "--verbose", "--print-certs", "--min-sdk-version", str(sdk), str(snapshot)], run,
                    failure="apk_signature_invalid")
                signers = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})\s*$", signed, re.M)
                count = re.findall(r"^Number of signers: (\d+)\s*$", signed, re.M)
                if count != ["1"] or len(signers) != 1:
                    raise VerificationError("multiple_or_missing_signers")
                signer = signers[0].lower()
                report["signerSha256"] = signer
                if signer != approved_signer_sha256 or (expected.signer_sha256 is not None and signer != expected.signer_sha256):
                    raise VerificationError("signer_not_approved")
                # APK v2 protects the entire archive. Enforce it for API27;
                # v1-only signatures and rotation/multiple identities are v2 work.
                if not re.search(r"^Verified using v2 scheme .*: true\s*$", signed, re.M):
                    raise VerificationError("apk_v2_signature_required")
                if re.search(r"^Signer #\d+ certificate DN:.*CN=Android Debug", signed, re.M | re.I):
                    raise VerificationError("debug_signer_forbidden")
            report["status"] = "verified"
            return VerifiedApk(package, version, name, sdk, tuple(abis), size, digest, signer, str(run / "report.json"))
        except VerificationError as exc:
            report.update(status="failed", errorCode=exc.code)
            raise VerificationError(exc.code, str(run / "report.json")) from exc
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, EOFError) as exc:
            report.update(status="failed", errorCode="verification_io_error")
            raise VerificationError("verification_io_error", str(run / "report.json")) from exc
        finally:
            report["completedAt"] = datetime.now(timezone.utc).isoformat()
            # Failing to persist evidence prevents returning a usable result.
            try:
                with (run / "report.json").open("x", encoding="utf-8") as output:
                    json.dump(report, output, ensure_ascii=False, indent=2)
            except OSError as exc:
                raise VerificationError("evidence_write_failed") from exc

    def _check_tools(self, report):
        for key, path in (("aapt2", self.tools.aapt2), ("java", self.tools.java), ("apksignerJar", self.tools.apksigner_jar)):
            if not path.is_absolute() or not path.is_file():
                raise VerificationError("tool_missing")
            # Operator-controlled files, pinned by digest in each evidence run.
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            report["tools"][key] = {"sha256": digest.hexdigest()}

    def _run(self, label, command, run, failure="tool_failed"):
        stdout_path, stderr_path = run / (label + ".stdout"), run / (label + ".stderr")
        # Never invoke a shell or pass business credentials to a child process.
        allowed = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        env.update(JAVA_HOME=str(self.tools.java.parent.parent), LC_ALL="C", LANG="C")
        env["PATH"] = os.pathsep.join((str(self.tools.java.parent), os.path.join(os.environ.get("SYSTEMROOT", "/"), "System32")))
        start = time.monotonic()
        code = None
        try:
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                with subprocess.Popen(command, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                        cwd=run, env=env, shell=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
                    try:
                        while process.poll() is None:
                            if time.monotonic() - start > self.tools.timeout_seconds:
                                raise VerificationError("tool_timeout")
                            if stdout_path.stat().st_size + stderr_path.stat().st_size > self.tools.output_limit_bytes:
                                raise VerificationError("tool_output_limit")
                            time.sleep(0.02)
                        code = process.returncode
                    finally:
                        if process.poll() is None:
                            process.kill()
                        process.wait()
            if stdout_path.stat().st_size + stderr_path.stat().st_size > self.tools.output_limit_bytes:
                raise VerificationError("tool_output_limit")
            if code != 0:
                raise VerificationError(failure)
            return stdout_path.read_text(encoding="utf-8", errors="strict")
        except FileNotFoundError as exc:
            raise VerificationError("tool_missing") from exc
        finally:
            (run / (label + ".result.json")).write_text(json.dumps(dict(exitCode=code,
                elapsedMs=round((time.monotonic() - start) * 1000))), encoding="utf-8")

    def _copy(self, stream, snapshot):
        size = 0
        digest = hashlib.sha256()
        start = time.monotonic()
        with snapshot.open("xb") as output:
            while True:
                if time.monotonic() - start > self.tools.stream_timeout_seconds:
                    raise VerificationError("stream_timeout")
                # Caller must also bound transport read timeouts. A blocked
                # read cannot be canceled by this synchronous verifier.
                block = stream.read(min(1024 * 1024, self.tools.max_bytes - size + 1))
                if not block:
                    break
                if not isinstance(block, bytes):
                    raise VerificationError("invalid_stream")
                size += len(block)
                if size > self.tools.max_bytes:
                    raise VerificationError("apk_too_large")
                digest.update(block)
                output.write(block)
        if size == 0:
            raise VerificationError("apk_empty")
        return size, digest.hexdigest()

    def _validate_zip(self, snapshot):
        try:
            with zipfile.ZipFile(snapshot) as apk:
                entries = apk.infolist()
                names = [entry.filename for entry in entries]
                if len(entries) > self.tools.max_entries or len(set(names)) != len(names):
                    raise VerificationError("apk_invalid_zip")
                if "AndroidManifest.xml" not in names:
                    raise VerificationError("apk_not_standalone")
                if sum(entry.file_size for entry in entries) > self.tools.max_expanded_bytes:
                    raise VerificationError("apk_expansion_limit")
                abis = set()
                for entry in entries:
                    name = entry.filename
                    if entry.flag_bits & 1 or "\\" in name or name.startswith("/") or ".." in name.split("/"):
                        raise VerificationError("apk_invalid_zip")
                    if name.startswith("lib/") and name.endswith(".so"):
                        parts = name.split("/")
                        if len(parts) != 3 or parts[1] not in ABIS:
                            raise VerificationError("apk_unsupported_abi")
                        abis.add(parts[1])
                # Read all entries and verify CRC without extraction or keeping
                # decompressed data in memory; bound expanded bytes separately.
                start = time.monotonic()
                expanded = 0
                for entry in entries:
                    with apk.open(entry) as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            expanded += len(block)
                            if expanded > self.tools.max_expanded_bytes:
                                raise VerificationError("apk_expansion_limit")
                            if time.monotonic() - start > self.tools.stream_timeout_seconds:
                                raise VerificationError("stream_timeout")
                return abis, "classes.dex" in names
        except (zipfile.BadZipFile, NotImplementedError, zlib.error) as exc:
            raise VerificationError("apk_invalid_zip") from exc

    @staticmethod
    def _parse_manifest(badging, tree, zip_abis):
        lines = badging.splitlines()
        packages = [line for line in lines if line.startswith("package: ")]
        sdk = re.findall(r"^minSdkVersion:'(\d+)'$", badging, re.M)
        if len(packages) != 1 or len(sdk) != 1:
            raise VerificationError("apk_manifest_invalid")
        pairs = re.findall(r"([A-Za-z][A-Za-z0-9_-]*)='([^'\r\n]*)'", packages[0])
        attrs = dict(pairs)
        if len(attrs) != len(pairs) or not {"name", "versionCode", "versionName"}.issubset(attrs):
            raise VerificationError("apk_manifest_invalid")
        # Avoid install-time splits, instant apps and codeMajor hidden behind
        # a low 32-bit version. v1 accepts a complete conventional APK only.
        if ("split" in attrs or re.search(r"^\s*A: (?:split=|.*:(?:isSplitRequired|isFeatureSplit|isolatedSplits|sharedUserId|isInstantApp))", tree, re.M)
                or "E: uses-split " in tree):
            raise VerificationError("apk_not_standalone")
        # v1 selection carries minSdk only. Never advertise an APK with an
        # unmodelled upper OS limit as compatible with every newer device.
        if re.search(r"^maxSdkVersion:", badging, re.M) or re.search(r":maxSdkVersion(?:\(|=)", tree):
            raise VerificationError("apk_max_sdk_unsupported")
        major = re.findall(r"versionCodeMajor(?:\(0x[0-9a-f]+\))?=(\S+)", tree)
        if major and major != ["0"]:
            raise VerificationError("apk_version_major_unsupported")
        if not attrs["versionCode"].isdigit() or not attrs["versionName"] or len(attrs["versionName"]) > 128:
            raise VerificationError("apk_manifest_invalid")
        version, minimum = int(attrs["versionCode"]), int(sdk[0])
        if not 1 <= version <= MAX_VERSION_CODE or not 27 <= minimum <= 10000:
            raise VerificationError("apk_version_or_sdk_unsupported")
        native = re.findall(r"^native-code: (.*)$", badging, re.M)
        if len(native) > 1:
            raise VerificationError("apk_manifest_invalid")
        reported = set(re.findall(r"'([^']+)'", native[0])) if native else set()
        if reported != zip_abis:
            raise VerificationError("apk_abi_mismatch")
        return attrs["name"], version, attrs["versionName"], minimum, sorted(zip_abis or ABIS)
