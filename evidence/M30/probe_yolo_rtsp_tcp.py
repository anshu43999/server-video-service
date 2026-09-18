import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import settings
from app.stream import OPENCV_FFMPEG_CAPTURE_OPTIONS, StreamSession


SOURCE_URL = "rtsp://127.0.0.1:18554/file-test"
PROBE_SECONDS = 20


DECODE_ERROR_MARKERS = (
    "Invalid level prefix",
    "corrupted macroblock",
    "Missing reference picture",
    "decode_slice_header error",
)


async def run_worker() -> None:
    settings.mediamtx_enabled = False
    session = StreamSession("m30-t04-yolo-probe", SOURCE_URL)
    try:
        await session.set_yolo(True)
        await session.start()
        await asyncio.sleep(PROBE_SECONDS)
        result = {
            "source": SOURCE_URL,
            "transport": settings.rtsp_transport,
            "opencvOptions": __import__("os").environ.get(
                OPENCV_FFMPEG_CAPTURE_OPTIONS,
            ),
            "yoloEnabled": session.yolo_enabled,
            "detectorError": session.detector.load_error,
            "state": session.state.value,
            "lastError": session.last_error,
            **session.metrics(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["opencvOptions"] is None or "rtsp_transport;tcp" not in result["opencvOptions"]:
            raise SystemExit("RTSP TCP capture option was not applied")
        if session.frames_received < 10:
            raise SystemExit("probe did not receive enough real RTSP frames")
        if session.frames_processed < 1:
            raise SystemExit("YOLO did not process any real RTSP frame")
        if session.last_error:
            raise SystemExit(f"stream session failed: {session.last_error}")
    finally:
        await session.close()


def main() -> None:
    if "--worker" in sys.argv:
        asyncio.run(run_worker())
        return

    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=PROBE_SECONDS + 30,
    )
    print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    if completed.returncode:
        raise SystemExit(completed.returncode)
    matched = [marker for marker in DECODE_ERROR_MARKERS if marker in completed.stderr]
    if matched:
        raise SystemExit(f"H.264 decoder errors detected: {', '.join(matched)}")


if __name__ == "__main__":
    main()
