"""Run APK verifier + worker integration on SDK tools and disposable PostgreSQL."""
import argparse
from pathlib import Path

from accept_m42_contract import main


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--android-jar", type=Path, required=True)
    parser.add_argument("--product-debug", type=Path)
    args = parser.parse_args()
    binary = "aapt2.exe" if (args.build_tools / "aapt2.exe").exists() else "aapt2"
    env = dict(RUN_APK_TOOL_TESTS="1", APK_TEST_AAPT2=str((args.build_tools / binary).resolve()),
        APK_TEST_JAVA=str(args.java.resolve()), APK_TEST_APKSIGNER_JAR=str((args.build_tools / "lib/apksigner.jar").resolve()),
        APK_TEST_ANDROID_JAR=str(args.android_jar.resolve()))
    if args.product_debug:
        env["APK_TEST_PRODUCT_DEBUG"] = str(args.product_debug.resolve())
    raise SystemExit(main(task="T02", patterns=("test_apk_verifier*.py", "test_apk_verification_jobs.py",
        "test_app_update_contract.py", "test_database.py"), test_env=env))
