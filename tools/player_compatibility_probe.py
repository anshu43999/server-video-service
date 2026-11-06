"""Retired mobile distribution probe; never open URLs or start players."""
import json


def main() -> int:
    print(json.dumps({"status": "retired", "error": "live_video_retired",
                      "message": "WHEP/LL-HLS playback is removed. Validate PC preview and RTSP input separately under M34-T06."}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
