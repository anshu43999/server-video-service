"""Probe MJPEG and WebSocket output contracts against a running service."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import cv2
import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def sample_jpeg() -> bytes:
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    image[:, :, 2] = 220
    ok, encoded = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError("cannot create sample JPEG")
    return encoded.tobytes()


def create_stream(base_url: str, stream_id: str) -> None:
    response = httpx.post(f"{base_url.rstrip('/')}/api/streams", json={"stream_id": stream_id}, timeout=5)
    if response.status_code not in (201, 409):
        response.raise_for_status()


async def connect(url: str):
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        from websockets import connect
    return connect(url)


async def probe_ws(server: str, stream_id: str, payload: bytes) -> dict:
    base = server.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    async with await connect(f"{base}/api/streams/{stream_id}/ingest") as ingest:
        async with await connect(f"{base}/api/streams/{stream_id}/ws") as output:
            await ingest.send(payload)
            result = await asyncio.wait_for(output.recv(), timeout=5)
            return {"bytes": len(result), "is_jpeg": result[:2] == b"\xff\xd8"}


def probe_mjpeg(base_url: str, stream_id: str) -> dict:
    response = httpx.get(
        f"{base_url.rstrip('/')}/api/streams/{stream_id}/mjpeg",
        timeout=5,
        headers={"Range": "bytes=0-2047"},
    )
    return {
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "has_boundary": "boundary=frame" in response.headers.get("content-type", ""),
    }


async def main_async(args: argparse.Namespace) -> int:
    payload = sample_jpeg()
    create_stream(args.server, args.stream_id)
    ws_result = await probe_ws(args.server, args.stream_id, payload)
    print(json.dumps({"websocket": ws_result, "note": "MJPEG probe requires a frame already available"}))
    return 0 if ws_result["is_jpeg"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe server output stream contracts")
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--stream-id", default="probe-output")
    args = parser.parse_args()
    try:
        return asyncio.run(main_async(args))
    except Exception as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
