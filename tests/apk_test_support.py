"""Build small real APKs with an ephemeral test key, outside product sources."""
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from app.app_updates.apk_verifier import Toolchain


def sdk_tools(root):
    evidence = Path(os.environ["APK_TEST_EVIDENCE_ROOT"]) / ("verification-" + uuid4().hex) if os.environ.get("APK_TEST_EVIDENCE_ROOT") else root / "evidence"
    return Toolchain(Path(os.environ["APK_TEST_AAPT2"]), Path(os.environ["APK_TEST_JAVA"]),
        Path(os.environ["APK_TEST_APKSIGNER_JAR"]), evidence, root / "staging")


class ApkFixtures:
    def __init__(self, root):
        self.root = root
        self.tools = sdk_tools(root)
        self.android_jar = Path(os.environ["APK_TEST_ANDROID_JAR"])
        self.key = root / "test-signing.p12"
        keytool = self.tools.java.with_name("keytool.exe" if os.name == "nt" else "keytool")
        self.run([str(keytool), "-genkeypair", "-keystore", str(self.key), "-storetype", "PKCS12",
            "-storepass", "fixture-only", "-keypass", "fixture-only", "-alias", "test", "-keyalg", "RSA",
            "-keysize", "2048", "-validity", "2", "-dname", "CN=Ephemeral APK Test,O=Test,C=CN", "-noprompt"])

    @staticmethod
    def run(command):
        # Never print command arguments: fixture passwords are not prod secrets,
        # but command output should follow the same no-credentials discipline.
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
        return result.stdout.decode("utf-8", errors="strict")

    def apk(self, name, *, version=1, package="com.aiyolo.inspection", sign=True, major=None, native_abi=None):
        work = self.root / name
        work.mkdir()
        manifest = work / "AndroidManifest.xml"
        major_attribute = f' android:versionCodeMajor="{major}"' if major is not None else ""
        manifest.write_text(f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
 package="{package}" android:versionCode="{version}" android:versionName="test.{version}"{major_attribute}>
 <uses-sdk android:minSdkVersion="27" android:targetSdkVersion="36"/>
 <application android:label="APK verifier test" android:hasCode="false"/>
</manifest>''', encoding="utf-8")
        unsigned = work / "unsigned.apk"
        self.run([str(self.tools.aapt2), "link", "-I", str(self.android_jar), "--manifest", str(manifest), "-o", str(unsigned)])
        # This is a valid resource-only APK, not an invented binary manifest.
        import zipfile
        with zipfile.ZipFile(unsigned, "a") as archive:
            if native_abi:
                archive.writestr(f"lib/{native_abi}/libfixture.so", b"fixture-library")
        if not sign:
            return unsigned
        signed = work / "signed.apk"
        self.run([str(self.tools.java), "-jar", str(self.tools.apksigner_jar), "sign", "--ks", str(self.key),
            "--ks-pass", "pass:fixture-only", "--key-pass", "pass:fixture-only", "--ks-key-alias", "test",
            "--v1-signing-enabled", "false", "--v2-signing-enabled", "true", "--v3-signing-enabled", "false",
            "--out", str(signed), str(unsigned)])
        return signed

    def signer(self, apk):
        import re
        output = self.run([str(self.tools.java), "-jar", str(self.tools.apksigner_jar), "verify", "--print-certs", str(apk)])
        return re.search(r"certificate SHA-256 digest: ([a-f0-9]{64})", output)[1]
