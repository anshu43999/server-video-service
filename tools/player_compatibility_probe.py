"""Probe WHEP, LL-HLS and RTSP endpoints without fabricating playback results.

The probe is intentionally conservative: an HTTP response only proves that an
endpoint answered.  WHEP video rendering and RTSP decoding require a real
browser/player and are reported as ``blocked`` when the required executable is
not installed.  JSON output is suitable for attaching to an M08-T08 record.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def percentile(values: list[float], p: float) -> float | None:
    """Return a linear-interpolated percentile, or None for no samples."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 3)


def probe_http(url: str, samples: int, timeout: float, *, expected: str | None = None) -> dict[str, Any]:
    timings: list[float] = []
    statuses: list[int] = []
    content_types: list[str] = []
    errors: list[str] = []
    for _ in range(max(1, samples)):
        started = time.perf_counter()
        try:
            with urlopen(Request(url, headers={"User-Agent": "aiyolo-player-probe/1"}), timeout=timeout) as response:
                body = response.read(4096)
                elapsed = (time.perf_counter() - started) * 1000
                timings.append(elapsed)
                statuses.append(response.status)
                content_types.append(response.headers.get("content-type", ""))
                if expected and expected not in body.decode("utf-8", errors="ignore"):
                    errors.append(f"response missing marker {expected!r}")
        except HTTPError as exc:
            errors.append(f"HTTP {exc.code}")
        except (TimeoutError, URLError, OSError) as exc:
            errors.append(str(exc.reason if isinstance(exc, URLError) else exc))
    ok = bool(timings) and not errors and all(200 <= status < 300 for status in statuses)
    return {
        "url": url,
        "status": "measured" if timings else "blocked",
        "http_ok": ok,
        "samples": len(timings),
        "first_byte_ms_p50": percentile(timings, 0.50),
        "first_byte_ms_p95": percentile(timings, 0.95),
        "http_statuses": statuses,
        "content_types": content_types,
        "errors": errors,
        "note": "HTTP timing is not video first-frame or end-to-end latency.",
    }


def probe_whep(url: str | None, offer_file: str | None, samples: int, timeout: float) -> dict[str, Any]:
    if not url:
        return {"status": "blocked", "reason": "no WHEP URL supplied"}
    if not offer_file:
        return {
            "url": url,
            "status": "blocked",
            "reason": "WHEP requires a browser-generated SDP offer; pass --whep-offer-file",
        }
    offer = Path(offer_file).read_bytes()
    timings: list[float] = []
    statuses: list[int] = []
    errors: list[str] = []
    for _ in range(max(1, samples)):
        started = time.perf_counter()
        try:
            request = Request(url, data=offer, method="POST", headers={"Content-Type": "application/sdp", "Accept": "application/sdp"})
            with urlopen(request, timeout=timeout) as response:
                response.read(4096)
                timings.append((time.perf_counter() - started) * 1000)
                statuses.append(response.status)
        except HTTPError as exc:
            errors.append(f"HTTP {exc.code}")
        except (TimeoutError, URLError, OSError) as exc:
            errors.append(str(exc.reason if isinstance(exc, URLError) else exc))
    return {
        "url": url,
        "status": "measured" if timings else "blocked",
        "http_ok": bool(timings) and not errors and all(200 <= code < 300 for code in statuses),
        "samples": len(timings),
        "signal_p50_ms": percentile(timings, 0.50),
        "signal_p95_ms": percentile(timings, 0.95),
        "http_statuses": statuses,
        "errors": errors,
        "note": "Signaling timing is not browser first-frame or end-to-end latency; capture those in the browser record.",
    }


def probe_rtsp(url: str | None, ffprobe: str | None, timeout: float) -> dict[str, Any]:
    if not url:
        return {"status": "blocked", "reason": "no RTSP URL supplied"}
    executable = ffprobe or shutil.which("ffprobe")
    if not executable:
        return {"url": url, "status": "blocked", "reason": "ffprobe is not installed"}
    try:
        completed = subprocess.run(
            [executable, "-v", "error", "-rtsp_transport", "tcp", "-show_entries", "stream=codec_name,width,height,r_frame_rate", "-of", "json", url],
            capture_output=True, text=True, timeout=timeout,
        )
        return {"url": url, "status": "measured" if completed.returncode == 0 else "blocked", "returncode": completed.returncode, "streams": json.loads(completed.stdout or "{}").get("streams", []), "stderr": completed.stderr[-1000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"url": url, "status": "blocked", "reason": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Non-fabricating WHEP/LL-HLS/RTSP compatibility probe")
    parser.add_argument("--whep-url")
    parser.add_argument("--whep-offer-file")
    parser.add_argument("--llhls-url")
    parser.add_argument("--rtsp-url")
    parser.add_argument("--ffprobe")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {
        "tool": "player_compatibility_probe",
        "version": 1,
        "generated_at_epoch_ms": round(time.time() * 1000),
        "whep": probe_whep(args.whep_url, args.whep_offer_file, args.samples, args.timeout),
        "llhls": probe_http(args.llhls_url, args.samples, args.timeout, expected="#EXTM3U") if args.llhls_url else {"status": "blocked", "reason": "no LL-HLS URL supplied"},
        "rtsp": probe_rtsp(args.rtsp_url, args.ffprobe, args.timeout),
        "frozen": False,
    }
    result["frozen"] = any(item.get("status") == "blocked" for item in (result["whep"], result["llhls"], result["rtsp"]))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
