from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


def main() -> None:
    port = int(os.environ.get("CONVERTER_PORT", "8090"))
    token = os.environ.get("CONVERTER_TOKEN", "")
    healthy = False
    try:
        request = Request(
            f"http://127.0.0.1:{port}/v1/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
        healthy = response.status == 200 and payload.get("protocolVersion") == 1
    except Exception:
        healthy = False
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
