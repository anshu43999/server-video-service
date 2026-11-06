"""Retired H.264 publishing benchmark; retained only to fail old invocations."""
import json


def main() -> int:
    print(json.dumps({"status": "retired", "error": "live_video_retired",
                      "message": "H.264 publishing is removed. Use ADR-003 and M34-T06 local analysis/preview acceptance."}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
