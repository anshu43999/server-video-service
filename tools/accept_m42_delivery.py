"""Release API and real dual-source delivery in a disposable PostgreSQL cluster."""
import argparse
from pathlib import Path
from accept_m42_contract import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--android-jar", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(main(task="T05",patterns=("test_app_update_*.py", "test_database.py"),test_env=dict(
        RUN_APP_DELIVERY_REAL="1", APK_TEST_AAPT2=str((args.build_tools / "aapt2.exe").resolve()),
        APK_TEST_JAVA=str(args.java.resolve()),
        APK_TEST_APKSIGNER_JAR=str((args.build_tools / "lib/apksigner.jar").resolve()),
        APK_TEST_ANDROID_JAR=str(args.android_jar.resolve()))))
