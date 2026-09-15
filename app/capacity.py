"""Reusable multi-stream capacity benchmark primitives.

The benchmark deliberately drives :class:`MediaMTXPublisher.publish`, which
performs H.264 encoding before writing to MediaMTX.  This prevents accidentally
reporting the old JPEG/no-encoding capacity as production capacity.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np


@dataclass
class CapacityResult:
    streams: int
    frames_requested: int
    frames_published: int
    elapsed_seconds: float
    target_fps: float
    encode_ms_p50: float | None
    encode_ms_p95: float | None
    effective_fps: float
    per_stream: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "h264-publish"
    resource_sample: dict[str, float | None] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "streams": self.streams,
            "frames_requested": self.frames_requested,
            "frames_published": self.frames_published,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "target_fps": self.target_fps,
            "effective_fps": round(self.effective_fps, 2),
            "encode_ms_p50": self.encode_ms_p50,
            "encode_ms_p95": self.encode_ms_p95,
            "per_stream": self.per_stream,
            "resource_sample": self.resource_sample,
        }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


async def run_capacity_benchmark(
    *,
    streams: int,
    frames: int,
    target_fps: float,
    frame: np.ndarray,
    publisher_factory: Callable[[str], Any],
    sample_resources: Callable[[], dict[str, float | None]] | None = None,
) -> CapacityResult:
    """Run concurrent streams against real or injected publishers.

    ``publisher_factory`` must return an object exposing async ``publish`` and
    ``close`` plus optional ``metrics``.  Production callers should construct
    ``MediaMTXPublisher(enabled=True)``; tests inject a deterministic fake.
    """
    if streams < 1 or frames < 1 or target_fps <= 0:
        raise ValueError("streams, frames and target_fps must be positive")
    publishers = [publisher_factory(f"capacity-{i + 1:03d}") for i in range(streams)]
    start = time.perf_counter()
    samples: list[float] = []

    async def worker(publisher: Any) -> dict[str, Any]:
        published = 0
        for _ in range(frames):
            ok = await publisher.publish(frame)
            # Measure encoder time separately from queue/write/reconnect time.
            # MediaMTXPublisher exposes the encoder metrics internally; test
            # doubles may expose ``encode_ms`` directly.
            metrics = publisher.metrics() if hasattr(publisher, "metrics") else {}
            encode_ms = (metrics or {}).get("encoder_last_ms")
            if encode_ms is None:
                encode_ms = getattr(publisher, "encode_ms", None)
            if encode_ms is not None:
                samples.append(float(encode_ms))
            published += int(bool(ok))
            # Keep the benchmark bounded while preserving concurrent pressure.
            await asyncio.sleep(1.0 / target_fps)
        metrics = publisher.metrics() if hasattr(publisher, "metrics") else {}
        metrics = dict(metrics or {})
        metrics.update({"stream_id": getattr(publisher, "stream_id", None), "frames_ok": published})
        return metrics

    try:
        per_stream = await asyncio.gather(*(worker(publisher) for publisher in publishers))
    finally:
        await asyncio.gather(*(publisher.close() for publisher in publishers), return_exceptions=True)
    elapsed = time.perf_counter() - start
    requested = streams * frames
    published = sum(int(item.get("frames_ok", 0)) for item in per_stream)
    return CapacityResult(
        streams=streams,
        frames_requested=requested,
        frames_published=published,
        elapsed_seconds=elapsed,
        target_fps=target_fps,
        effective_fps=published / elapsed if elapsed else 0.0,
        encode_ms_p50=_percentile(samples, 0.50),
        encode_ms_p95=_percentile(samples, 0.95),
        per_stream=per_stream,
        resource_sample=sample_resources() if sample_resources else {},
    )


def default_resource_sample() -> dict[str, float | None]:
    """Best-effort process resource sample; unavailable metrics remain null."""
    try:
        import psutil  # type: ignore

        process = psutil.Process()
        return {
            "cpu_percent": process.cpu_percent(interval=0.05),
            "memory_mb": round(process.memory_info().rss / 1024 / 1024, 2),
            "system_memory_percent": psutil.virtual_memory().percent,
        }
    except Exception:
        return {"cpu_percent": None, "memory_mb": None, "system_memory_percent": None}
