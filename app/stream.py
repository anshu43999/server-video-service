from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

import cv2

from .config import settings
from .detector import YoloDetector, decode_image
from .protocol import InputRateLimitError, MAX_FRAME_BYTES, MAX_FRAME_HEIGHT, MAX_FRAME_WIDTH, StreamState


@dataclass
class StreamSession:
    stream_id: str
    source_url: str | int | None = None
    detector: YoloDetector = field(
        default_factory=lambda: YoloDetector(
            settings.yolo_model_path,
            settings.yolo_confidence,
            settings.yolo_imgsz,
            settings.yolo_device,
            [item.strip() for item in settings.yolo_classes.split(",") if item.strip()]
            if settings.yolo_classes
            else None,
        )
    )
    yolo_enabled: bool = False
    max_fps: float = field(default_factory=lambda: settings.max_fps)
    latest_jpeg: bytes | None = None
    frames_received: int = 0
    frames_processed: int = 0
    frames_dropped: int = 0
    frames_fallback: int = 0
    last_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    processed_fps: float = 0.0
    output_fps: float = 0.0
    last_error: str | None = None
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition, init=False)
    _pull_task: asyncio.Task | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)
    _last_emit: float = field(default=0.0, init=False)
    _last_input: float = field(default=0.0, init=False)
    _active_subscribers: int = field(default=0, init=False)
    _pending_frame: object | None = field(default=None, init=False)
    _processing_task: asyncio.Task | None = field(default=None, init=False)
    _received_times: list[float] = field(default_factory=list, init=False)
    _processed_times: list[float] = field(default_factory=list, init=False)
    _output_times: list[float] = field(default_factory=list, init=False)
    _latencies: list[float] = field(default_factory=list, init=False)
    _last_frame_received_at: float | None = field(default=None, init=False)
    _state: StreamState = field(default=StreamState.CREATED, init=False)

    @property
    def state(self) -> StreamState:
        return self._state

    async def start(self):
        if self.source_url is not None and self._pull_task is None:
            self._pull_task = asyncio.create_task(self._pull_loop())

    async def close(self):
        self._closed = True
        self._state = StreamState.CLOSED
        if self._pull_task:
            self._pull_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pull_task
        if self._processing_task:
            self._processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task
        async with self._condition:
            self._condition.notify_all()

    async def set_yolo(self, enabled: bool):
        self.yolo_enabled = enabled
        if enabled:
            self.detector._load()
        elif self._pending_frame is not None:
            self._pending_frame = None

    async def _publish_frame(self, frame) -> None:
        now = time.monotonic()
        min_interval = 1.0 / max(self.max_fps, 1.0)
        if now - self._last_emit < min_interval:
            return
        self._last_emit = now
        ok, encoded = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), max(10, min(settings.jpeg_quality, 100))]
        )
        if not ok:
            raise ValueError("failed to encode processed frame")
        async with self._condition:
            self.latest_jpeg = encoded.tobytes()
            self.last_error = None
            self._state = StreamState.OUTPUTTING
            emitted_at = time.monotonic()
            self._output_times.append(emitted_at)
            self._output_times = self._output_times[-60:]
            self.output_fps = self._window_fps(self._output_times)
            self._condition.notify_all()

    @staticmethod
    def _window_fps(timestamps: list[float]) -> float:
        if len(timestamps) < 2:
            return 0.0
        elapsed = timestamps[-1] - timestamps[0]
        return round((len(timestamps) - 1) / elapsed, 2) if elapsed > 0 else 0.0

    def metrics(self) -> dict:
        return {
            "frames_received": self.frames_received,
            "frames_processed": self.frames_processed,
            "frames_dropped": self.frames_dropped,
            "frames_fallback": self.frames_fallback,
            "received_fps": self._window_fps(self._received_times),
            "processed_fps": self.processed_fps,
            "output_fps": self.output_fps,
            "last_latency_ms": self.last_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "active_subscribers": self.active_subscribers,
        }

    async def _yolo_worker(self):
        while not self._closed:
            frame = self._pending_frame
            self._pending_frame = None
            if frame is None:
                return
            try:
                if self.detector.load_error:
                    processed = frame
                    self.frames_fallback += 1
                else:
                    processed = await asyncio.to_thread(self.detector.annotate, frame)
                    self.frames_processed += 1
                finished_at = time.monotonic()
                self._processed_times.append(finished_at)
                self._processed_times = self._processed_times[-60:]
                self.processed_fps = self._window_fps(self._processed_times)
                if self._last_frame_received_at is not None:
                    latency = (finished_at - self._last_frame_received_at) * 1000
                    self.last_latency_ms = round(latency, 2)
                    self._latencies.append(latency)
                    self._latencies = self._latencies[-100:]
                    ordered = sorted(self._latencies)
                    index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
                    self.p95_latency_ms = round(ordered[index], 2)
                await self._publish_frame(processed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                self._state = StreamState.ERROR

    async def ingest_jpeg(self, payload: bytes):
        if len(payload) > MAX_FRAME_BYTES:
            raise ValueError(f"frame exceeds {MAX_FRAME_BYTES} bytes")
        now = time.monotonic()
        min_input_interval = 1.0 / max(settings.max_input_fps, 1.0)
        if self._last_input and now - self._last_input < min_input_interval:
            raise InputRateLimitError("input frame rate exceeds configured limit")
        self._last_input = now
        frame = decode_image(payload)
        height, width = frame.shape[:2]
        if width > MAX_FRAME_WIDTH or height > MAX_FRAME_HEIGHT:
            raise ValueError(f"frame exceeds {MAX_FRAME_WIDTH}x{MAX_FRAME_HEIGHT}")
        self._state = StreamState.INGESTING
        self.frames_received += 1
        self._last_frame_received_at = now
        self._received_times.append(now)
        self._received_times = self._received_times[-60:]
        if self.yolo_enabled:
            if self._pending_frame is not None:
                self.frames_dropped += 1
            self._pending_frame = frame
            if self._processing_task is None or self._processing_task.done():
                self._processing_task = asyncio.create_task(self._yolo_worker())
            return
        await self._publish_frame(frame)

    async def wait_frame(self, previous: bytes | None = None) -> bytes | None:
        async with self._condition:
            # Compare object identity: two consecutive frames may encode to identical bytes.
            await self._condition.wait_for(lambda: self._closed or self.latest_jpeg is not previous)
            return self.latest_jpeg

    def try_subscribe(self) -> bool:
        if self._active_subscribers >= settings.max_output_subscribers:
            return False
        self._active_subscribers += 1
        return True

    def unsubscribe(self) -> None:
        self._active_subscribers = max(0, self._active_subscribers - 1)

    @property
    def active_subscribers(self) -> int:
        return self._active_subscribers

    async def _pull_loop(self):
        while not self._closed:
            capture = cv2.VideoCapture(self.source_url)
            try:
                if not capture.isOpened():
                    raise RuntimeError(f"cannot open source: {self.source_url}")
                while not self._closed:
                    ok, frame = await asyncio.to_thread(capture.read)
                    if not ok:
                        break
                    ok, encoded = cv2.imencode(".jpg", frame)
                    if ok:
                        await self.ingest_jpeg(encoded.tobytes())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                self._state = StreamState.ERROR
            finally:
                capture.release()
            if not self._closed:
                await asyncio.sleep(1)
