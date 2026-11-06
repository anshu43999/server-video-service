"""Run T09 only against a disposable PostgreSQL and a random MinIO bucket."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from accept_m42_contract import main

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--build-tools",type=Path,required=True)
    parser.add_argument("--java",type=Path,required=True)
    parser.add_argument("--android-jar",type=Path,required=True)
    parser.add_argument("--chromium",type=Path,required=True)
    args=parser.parse_args()
    evidence=Path(__file__).resolve().parents[1]/"harness/evidence/M42"/("T09-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-live")
    raise SystemExit(main(task="T09-live",patterns=["test_app_update_live.py"],test_timeout=600,test_env=dict(
        RUN_APP_UPDATE_LIVE="1",APK_TEST_EVIDENCE_ROOT=str(evidence),
        PLAYWRIGHT_CHROMIUM_EXECUTABLE=str(args.chromium.resolve()),
        APK_TEST_AAPT2=str((args.build_tools/"aapt2.exe").resolve()),APK_TEST_JAVA=str(args.java.resolve()),
        APK_TEST_APKSIGNER_JAR=str((args.build_tools/"lib/apksigner.jar").resolve()),APK_TEST_ANDROID_JAR=str(args.android_jar.resolve()))))
