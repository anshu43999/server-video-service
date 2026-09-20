from __future__ import annotations

import json
import os
import sys
from urllib.request import urlopen


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    try:
        with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as response:
            payload = json.load(response)
        healthy = response.status == 200 and payload.get("status") == "ok"
    except Exception:
        healthy = False
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
