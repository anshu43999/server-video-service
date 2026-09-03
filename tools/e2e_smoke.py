"""In-process end-to-end smoke test for ingest -> processing -> output."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient

from app.main import app, streams


def run(source: str, stream_id: str, frames: int = 10) -> dict:
    capture = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not capture.isOpened():
        raise RuntimeError(f"cannot open source: {source}")
    latencies = []
    stream_state = None
    try:
        with TestClient(app) as client:
            streams.clear()
            created = client.post("/api/streams", json={"stream_id": stream_id})
            created.raise_for_status()
            with client.websocket_connect(f"/api/streams/{stream_id}/ingest") as ingest:
                with client.websocket_connect(f"/api/streams/{stream_id}/ws") as output:
                    for _ in range(frames):
                        ok, frame = capture.read()
                        if not ok:
                            break
                        encoded_ok, encoded = cv2.imencode(".jpg", frame)
                        if not encoded_ok:
                            raise RuntimeError("failed to encode source frame")
                        started = time.perf_counter()
                        ingest.send_bytes(encoded.tobytes())
                        received = output.receive_bytes()
                        latencies.append((time.perf_counter() - started) * 1000)
                        if not received.startswith(b"\xff\xd8"):
                            raise RuntimeError("output is not a JPEG")
                        # Respect the service's default 20 FPS output cap.
                        time.sleep(0.06)
                    stream_state = streams[stream_id].state.value
    finally:
        capture.release()
    if not latencies:
        raise RuntimeError("source produced no frames")
    return {
        "frames": len(latencies),
        "latency_ms_p50": round(statistics.median(latencies), 2),
        "latency_ms_max": round(max(latencies), 2),
        "stream_state": stream_state,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ingest/output smoke test")
    parser.add_argument("--source", required=True)
    parser.add_argument("--stream-id", default="e2e-smoke")
    parser.add_argument("--frames", type=int, default=10)
    args = parser.parse_args()
    print(run(args.source, args.stream_id, args.frames))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
