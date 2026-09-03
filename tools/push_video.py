"""Push a local video/camera source to the server ingest WebSocket."""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

import cv2
import httpx


def parse_source(value: str):
    return int(value) if value.isdigit() else value


def create_session(base_url: str, stream_id: str, source_url: str | None) -> None:
    response = httpx.post(
        f"{base_url.rstrip('/')}/api/streams",
        json={"stream_id": stream_id, "source_url": source_url},
        timeout=10,
    )
    if response.status_code == 409:
        return
    response.raise_for_status()


async def websocket_connect(url: str, headers: dict[str, str]):
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        from websockets import connect
    return connect(url, additional_headers=headers)


async def push(args: argparse.Namespace) -> int:
    source = parse_source(args.source)
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError(f"cannot open source: {args.source}")
    input_fps = capture.get(cv2.CAP_PROP_FPS)
    target_fps = args.fps or (input_fps if input_fps and input_fps > 1 else 15.0)
    target_fps = min(max(target_fps, 1.0), 30.0)
    interval = 1.0 / target_fps
    ws_url = args.server.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    ws_url += f"/api/streams/{args.stream_id}/ingest"
    headers = {"X-Video-Service-Token": args.token} if args.token else {}
    sent = 0
    deadline = time.monotonic() + args.duration if args.duration else None
    try:
        async with await websocket_connect(ws_url, headers) as websocket:
            while deadline is None or time.monotonic() < deadline:
                ok, frame = capture.read()
                if not ok:
                    if args.loop and isinstance(source, (str, Path)):
                        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    break
                encoded_ok, encoded = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), args.quality]
                )
                if not encoded_ok:
                    raise RuntimeError("failed to encode frame as JPEG")
                await websocket.send(encoded.tobytes())
                sent += 1
                if args.verbose and sent % max(1, int(target_fps)) == 0:
                    print(f"sent={sent} fps={target_fps:.1f}")
                await asyncio.sleep(interval)
    finally:
        capture.release()
    print(f"completed: sent {sent} JPEG frames at target {target_fps:.1f} FPS")
    return sent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Push a local video source to Server Video Service")
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--stream-id", required=True)
    parser.add_argument("--source", required=True, help="Video path, RTSP URL, or camera index")
    parser.add_argument("--fps", type=float, help="Target FPS, capped at 30")
    parser.add_argument("--quality", type=int, default=80, choices=range(10, 101), metavar="10-100")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--token")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.create:
        create_session(args.server, args.stream_id, None)
    try:
        return asyncio.run(push(args))
    except KeyboardInterrupt:
        print("stopped")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
