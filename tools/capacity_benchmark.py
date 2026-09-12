"""Concurrent H.264 + MediaMTX capacity benchmark.

Examples (run from server-video-service):
  .venv\\Scripts\\python.exe tools/capacity_benchmark.py --streams 4 --duration 20 --dry-run
  .venv\\Scripts\\python.exe tools/capacity_benchmark.py --streams 4 --duration 60 --publish

The default is a dry-run with a deterministic sink. ``--publish`` starts the
actual FFmpeg/MediaMTX publisher and therefore requires FFmpeg and a reachable
MediaMTX RTSP endpoint. Results are JSON so they can be archived verbatim.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import numpy as np

from app.capacity import default_resource_sample, run_capacity_benchmark
from app.publisher import MediaMTXPublisher, PublisherConfig


class NullPublisher:
    """Deterministic sink retaining the H.264 encode path in dry-run mode."""

    def __init__(self, stream_id: str, encoder_factory):
        self.stream_id = stream_id
        self._encoder = encoder_factory()
        self.frames_published = 0
        self.bytes_published = 0

    async def publish(self, frame: np.ndarray) -> bool:
        payload = await asyncio.to_thread(self._encoder.encode, frame)
        self.frames_published += 1
        self.bytes_published += len(payload)
        return True

    async def close(self) -> None:
        return None

    def metrics(self) -> dict[str, object]:
        metrics = self._encoder.metrics.as_dict()
        metrics.update({"frames_published": self.frames_published, "bytes_published": self.bytes_published})
        return metrics


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--streams", type=int, default=1, help="concurrent stream count")
    p.add_argument("--duration", type=float, default=10.0, help="seconds per run")
    p.add_argument("--fps", type=float, default=10.0, help="target FPS per stream")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=360)
    p.add_argument("--bitrate", default="2500k")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true", help="publish to MediaMTX instead of a sink")
    mode.add_argument("--dry-run", action="store_true", help="H.264 encode with deterministic sink (default)")
    p.add_argument("--rtsp-base", default="rtsp://127.0.0.1:8554")
    p.add_argument("--ffmpeg-path")
    p.add_argument("--output", type=Path, help="write JSON result to this path")
    return p


async def run(args: argparse.Namespace) -> dict[str, object]:
    if args.duration <= 0 or args.fps <= 0:
        raise ValueError("duration and fps must be positive")
    frames = max(1, round(args.duration * args.fps))
    # A fixed non-uniform frame makes encoder work representative and results
    # reproducible without requiring a camera or model weight.
    frame = np.zeros((args.height, args.width, 3), dtype=np.uint8)
    frame[:, :, 1] = 96
    frame[::8, ::8, 2] = 255

    def encoder_factory():
        from app.encoder import EncoderConfig, H264Encoder

        return H264Encoder(
            EncoderConfig(args.width, args.height, fps=args.fps, bitrate=args.bitrate),
            ffmpeg_path=args.ffmpeg_path,
        )

    if args.publish:
        def factory(stream_id: str):
            return MediaMTXPublisher(
                stream_id,
                PublisherConfig(enabled=True, base_url=args.rtsp_base, ffmpeg_path=args.ffmpeg_path),
            )
        mode = "h264-mediamtx-publish"
    else:
        factory = lambda stream_id: NullPublisher(stream_id, encoder_factory)
        mode = "h264-encoded-dry-run"

    result = await run_capacity_benchmark(
        streams=args.streams,
        frames=frames,
        target_fps=args.fps,
        frame=frame,
        publisher_factory=factory,
        sample_resources=default_resource_sample,
    )
    payload = result.as_dict()
    payload["mode"] = mode
    payload["frame"] = {"width": args.width, "height": args.height}
    payload["duration_requested_seconds"] = args.duration
    payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return payload


def main() -> int:
    args = parser().parse_args()
    try:
        payload = asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
