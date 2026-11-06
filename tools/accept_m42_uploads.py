"""Real APK upload acceptance in an isolated DB and disposable MinIO bucket."""
import argparse
from pathlib import Path
from accept_m42_contract import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--android-jar", type=Path, required=True)
    args = parser.parse_args()
    env = dict(RUN_APK_MINIO_TESTS="1", RUN_APK_TOOL_TESTS="1",
        APK_TEST_AAPT2=str((args.build_tools / "aapt2.exe").resolve()),
        APK_TEST_JAVA=str(args.java.resolve()), APK_TEST_APKSIGNER_JAR=str((args.build_tools / "lib/apksigner.jar").resolve()),
        APK_TEST_ANDROID_JAR=str(args.android_jar.resolve()))
    raise SystemExit(main(task="T03", patterns=("test_apk_uploads.py", "test_apk_minio_store.py",
        "test_apk_verification_jobs.py", "test_app_update_storage.py", "test_database.py", "test_app_update_contract.py"), test_env=env))
