from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import cv2

from .config import settings
from .detection import FrameDetections
from .detector import YoloDetector, decode_image
from .overlay import draw_overlay
from .protocol import InputRateLimitError, MAX_FRAME_BYTES, MAX_FRAME_HEIGHT, MAX_FRAME_WIDTH, StreamState
from .stream_config import redact_source_url
from .database import DEFAULT_PROJECT_ID


OPENCV_FFMPEG_CAPTURE_OPTIONS = "OPENCV_FFMPEG_CAPTURE_OPTIONS"


def _open_video_capture(source: str | int):
    """Open RTSP through FFmpeg with an explicit reliable transport."""
    if not isinstance(source, str) or not source.lower().startswith(("rtsp://", "rtsps://")):
        return cv2.VideoCapture(source)

    existing = os.environ.get(OPENCV_FFMPEG_CAPTURE_OPTIONS, "")
    options = [
        item
        for item in existing.split("|")
        if item and not item.lower().startswith("rtsp_transport;")
    ]
    options.append(f"rtsp_transport;{settings.rtsp_transport}")
    os.environ[OPENCV_FFMPEG_CAPTURE_OPTIONS] = "|".join(options)
    return cv2.VideoCapture(source, cv2.CAP_FFMPEG)


class _FrameRateLimiter:
    """Token bucket that caps average FPS while tolerating network jitter."""

    def __init__(self, burst: float = 8.0) -> None:
        self._burst = burst
        self._tokens = burst
        self._updated_at: float | None = None
        self._fps: float | None = None

    def allow(self, now: float, fps: float) -> bool:
        fps = max(fps, 1.0)
        if self._updated_at is None or self._fps != fps:
            self._updated_at = now
            self._fps = fps
        else:
            self._tokens = min(
                self._burst,
                self._tokens + max(0.0, now - self._updated_at) * fps,
            )
            self._updated_at = now
        if self._tokens + 1e-9 < 1.0:
            return False
        self._tokens = max(0.0, self._tokens - 1.0)
        return True


@dataclass
class StreamSession:
    stream_id: str
    source_url: str | int | None = None
    project_id: str = DEFAULT_PROJECT_ID
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
    overlay_enabled: bool = field(default_factory=lambda: settings.yolo_overlay)
    max_fps: float = field(default_factory=lambda: settings.max_fps)
    latest_jpeg: bytes | None = None
    latest_detections: FrameDetections | None = None
    frame_seq: int = 0
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
    # 检测旁路使用独立条件变量，避免视频消费者与元数据消费者相互阻塞。
    _detection_condition: asyncio.Condition = field(default_factory=asyncio.Condition, init=False)
    _detection_version: int = field(default=0, init=False)
    _pull_task: asyncio.Task | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)
    _last_emit: float = field(default=0.0, init=False)
    _last_input: float = field(default=0.0, init=False)
    _active_subscribers: int = field(default=0, init=False)
    _pending_frame: object | None = field(default=None, init=False)
    _processing_task: asyncio.Task | None = field(default=None, init=False)
    _received_times: list[float] = field(default_factory=list, init=False)
    _processed_times: list[float] = field(default_factory=list, init=False)
    _latencies: list[float] = field(default_factory=list, init=False)
    _last_frame_received_at: float | None = field(default=None, init=False)
    _last_captured_at_us: int = field(default=0, init=False)
    _state: StreamState = field(default=StreamState.CREATED, init=False)
    _analysis_generation: int = field(default=0, init=False)
    # Bounded, in-memory admin preview. JPEG work happens only on a PC request;
    # it is never a publisher and never gates inference or alert persistence.
    _preview_frame: Any | None = field(default=None, init=False)
    _preview_result: Any | None = field(default=None, init=False)
    _preview_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _preview_cache: Any | None = field(default=None, init=False)
    model_catalog_id: str | None = field(default=None, init=False)
    model_version: str | None = field(default=None, init=False)
    model_scenario: str | None = field(default=None, init=False)
    alert_runtime: Any | None = None
    model_authorizer: Any | None = None
    alert_error: str | None = None

    @property
    def state(self) -> StreamState:
        return self._state

    @property
    def closed(self) -> bool:
        return self._closed

    async def start(self):
        if self.source_url is not None and self._pull_task is None:
            self._pull_task = asyncio.create_task(self._pull_loop())

    async def close(self):
        self._closed = True
        self._analysis_generation += 1
        self._state = StreamState.CLOSED
        # Wake internal observers before waiting for capture/inference cleanup.
        async with self._condition:
            self._condition.notify_all()
        async with self._detection_condition:
            self._detection_condition.notify_all()
        if self._pull_task:
            self._pull_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pull_task
        if self._processing_task:
            self._processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task
        self._pending_frame = None
        self.latest_detections = None
        self._preview_frame = None
        self._preview_result = None
        self._preview_cache = None

    async def set_yolo(self, enabled: bool):
        self._analysis_generation += 1
        self.yolo_enabled = enabled
        self._preview_result = None
        self._preview_cache = None
        self.latest_detections = None
        self._pending_frame = None
        if enabled:
            self.detector._load()
        else:
            self._state = StreamState.INGESTING if self.frames_received else StreamState.CREATED
        async with self._detection_condition:
            self._detection_condition.notify_all()

    def bind_model(self, *, model_id: str, model_path: str, scenario: str | None = None,
                   labels: list[str] | None = None,
                   imgsz: int | None = None, device: str | None = None,
                   version: str | None = None, detection: dict | None = None,
                   enabled_labels: list[str] | None = None) -> dict:
        """Switch only this stream to a validated registered model.

        A fresh detector is used so its lazy-loaded runtime and error state cannot
        leak into another stream (or retain the previously bound model).
        """
        self._analysis_generation += 1
        self.latest_detections = None
        self._preview_result = None
        self._preview_cache = None
        self._pending_frame = None
        previous = self.detector
        self.detector = YoloDetector(
            model_path,
            detection["confidenceThreshold"] if detection is not None else previous.confidence,
            int(imgsz or previous.imgsz),
            "cpu",
            labels or None,
            model_id=model_id,
            iou=detection["iouThreshold"] if detection is not None else previous.iou,
            max_detections=detection["maxDetections"] if detection is not None else previous.max_detections,
            enabled_labels=enabled_labels,
        )
        self.model_catalog_id = model_id
        self.model_version = version
        self.model_scenario = scenario
        return self.model_metadata()

    def model_metadata(self) -> dict:
        metadata = self.detector.metadata()
        metadata.update({"catalog_model_id": self.model_catalog_id or metadata.get("model_id"),
                         "modelId": self.model_catalog_id or metadata.get("model_id"),
                         "modelVersion": self.model_version,
                         "scenario": self.model_scenario})
        return metadata

    async def _wait_for_analysis_slot(self) -> None:
        """Pace inference while input retains only the latest pending frame."""
        now = time.monotonic()
        interval = 1.0 / max(self.max_fps, 1.0)
        if not self._last_emit:
            self._last_emit = now
            return
        target = self._last_emit + interval
        if target > now:
            await asyncio.sleep(target - now)
            self._last_emit = target
        else:
            self._last_emit = now

    @staticmethod
    def _window_fps(timestamps: list[float]) -> float:
        if len(timestamps) < 2:
            return 0.0
        elapsed = timestamps[-1] - timestamps[0]
        return round((len(timestamps) - 1) / elapsed, 2) if elapsed > 0 else 0.0

    def metrics(self) -> dict:
        result = {
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
            "detections_last": self.latest_detections.result.detection_count if self.latest_detections else 0,
            "alert_error": self.alert_error,
        }
        # Legacy metric keys remain truthful while clients migrate to analysis status.
        result.update({"publish_state": "retired", "viewers": 0, "frames_published": 0})
        return result

    async def _yolo_worker(self):
        while not self._closed:
            if self._pending_frame is None:
                return
            await self._wait_for_analysis_slot()
            pending = self._pending_frame
            self._pending_frame = None
            if pending is None:
                return
            frame, frame_seq, captured_at_us, generation, received_at = pending
            detector = self.detector

            def current() -> bool:
                return (
                    not self._closed and self.yolo_enabled
                    and generation == self._analysis_generation
                    and detector is self.detector
                    and (self.model_authorizer is None or self.model_authorizer())
                )

            try:
                if not current():
                    self.latest_detections = None
                    continue
                if detector.load_error:
                    self.latest_detections = None
                    self._preview_result = None
                    self._preview_cache = None
                    self.frames_fallback += 1
                    self._state = StreamState.ERROR
                    self.last_error = "analysis model unavailable"
                    continue
                self._state = StreamState.ANALYZING
                result = await asyncio.to_thread(detector.infer, frame)
                # Stop/restart, rebind and authorization changes invalidate in-flight work.
                if not current():
                    self.latest_detections = None
                    continue
                if result.fallback_reason:
                    self.latest_detections = None
                    self._preview_result = None
                    self._preview_cache = None
                    self.frames_fallback += 1
                    self._state = StreamState.ERROR
                    self.last_error = "analysis inference unavailable"
                    continue
                self.latest_detections = FrameDetections(
                    self.stream_id, frame_seq, captured_at_us, result
                )
                self._preview_result = (frame, result, received_at, generation)
                async with self._detection_condition:
                    self._detection_version += 1
                    self._detection_condition.notify_all()
                self.frames_processed += 1
                finished_at = time.monotonic()
                self._processed_times.append(finished_at)
                self._processed_times = self._processed_times[-60:]
                self.processed_fps = self._window_fps(self._processed_times)
                latency = (finished_at - received_at) * 1000
                self.last_latency_ms = round(latency, 2)
                self._latencies.append(latency)
                self._latencies = self._latencies[-100:]
                ordered = sorted(self._latencies)
                index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
                self.p95_latency_ms = round(ordered[index], 2)
                self.last_error = None
                # Alert persistence is independent of PC preview requests.
                # No publisher or media server is involved.
                if self.alert_runtime is not None:
                    try:
                        evidence_frame = draw_overlay(frame, result.detections) if self.overlay_enabled else frame
                        self.alert_runtime.process(
                            project_id=self.project_id,
                            source_id=self.stream_id,
                            captured_at_us=captured_at_us,
                            result=result,
                            frame=evidence_frame,
                            evidence_baked_in=self.overlay_enabled,
                        )
                        self.alert_error = None
                    except Exception:
                        self.alert_error = "alert persistence or delivery failed"
            except asyncio.CancelledError:
                raise
            except Exception:
                self.latest_detections = None
                self._preview_result = None
                self._preview_cache = None
                self.last_error = "analysis processing failed"
                self._state = StreamState.ERROR

    async def ingest_jpeg(self, payload: bytes):
        if len(payload) > MAX_FRAME_BYTES:
            raise ValueError(f"frame exceeds {MAX_FRAME_BYTES} bytes")
        await self.ingest_frame(decode_image(payload))

    async def ingest_frame(
        self,
        frame,
        *,
        enforce_rate_limit: bool = True,
        pace_output: bool = True,
    ) -> None:
        """Ingest an already decoded BGR frame without a lossy JPEG round trip."""
        if self._closed:
            raise ValueError("stream is closed")
        now = time.monotonic()
        min_input_interval = 1.0 / max(settings.max_input_fps, 1.0)
        if enforce_rate_limit and self._last_input and now - self._last_input < min_input_interval:
            raise InputRateLimitError("input frame rate exceeds configured limit")
        self._last_input = now
        if frame is None or not hasattr(frame, "shape") or len(frame.shape) != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be a HxWx3 BGR image")
        height, width = frame.shape[:2]
        if width > MAX_FRAME_WIDTH or height > MAX_FRAME_HEIGHT:
            raise ValueError(f"frame exceeds {MAX_FRAME_WIDTH}x{MAX_FRAME_HEIGHT}")
        self._state = StreamState.INGESTING
        self.frames_received += 1
        self.frame_seq += 1
        # 采集时间戳只在接入层取，且同一路流单调不减（告警引擎 §4.1 的硬要求）。
        captured_at_us = max(self._last_captured_at_us, time.time_ns() // 1000)
        self._last_captured_at_us = captured_at_us
        self._last_frame_received_at = now
        self._preview_frame = frame
        self._received_times.append(now)
        self._received_times = self._received_times[-60:]
        if self.yolo_enabled:
            if self._pending_frame is not None:
                self.frames_dropped += 1
            self._pending_frame = (frame, self.frame_seq, captured_at_us, self._analysis_generation, now)
            if self._processing_task is None or self._processing_task.done():
                self._processing_task = asyncio.create_task(self._yolo_worker())
            return
        # YOLO disabled: the PC may request the raw preview; no background relay.
        self.last_error = None

    async def admin_preview(self) -> tuple[bytes, str] | None:
        """Latest PC snapshot, capped at 5 JPEG encodes/sec and 1280px width.

        A stale/disconnected source never returns a frozen last frame. Only a
        matching, still-authorized inference generation may supply an overlay.
        Legacy wait_frame/subscription APIs intentionally remain retired.
        """
        async with self._preview_lock:
            now = time.monotonic()
            if self._closed or self._preview_frame is None or self._last_frame_received_at is None:
                return None
            if now - self._last_frame_received_at > 3.0:
                self._preview_cache = None
                return None
            generation = self._analysis_generation
            authorized = self.model_authorizer is None or self.model_authorizer()
            candidate = self._preview_result
            annotated = bool(self.yolo_enabled and self.overlay_enabled and authorized
                             and candidate is not None and candidate[3] == generation
                             and now - candidate[2] <= 2.0)
            mode = "yolo" if annotated else "raw"
            key = (generation, mode)
            if self._preview_cache is not None:
                cached_at, cached_key, payload = self._preview_cache
                if cached_key == key and now - cached_at < 0.2:
                    return payload, mode
            frame = candidate[0] if annotated else self._preview_frame

            def encode():
                image = draw_overlay(frame, candidate[1].detections) if annotated else frame
                height, width = image.shape[:2]
                if width > 1280:
                    image = cv2.resize(image, (1280, max(1, int(height * 1280 / width))))
                ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
                return data.tobytes() if ok else None

            payload = await asyncio.to_thread(encode)
            # Recheck after encoding: shutdown/rebind/revocation may happen while
            # the worker thread runs. The HTTP layer also rechecks project access.
            if (self._closed or generation != self._analysis_generation
                    or time.monotonic() - self._last_frame_received_at > 3.0
                    or (annotated and (not self.overlay_enabled or
                        (self.model_authorizer is not None and not self.model_authorizer())))):
                return None
            if payload is None:
                return None
            self._preview_cache = (now, key, payload)
            return payload, mode

    async def set_max_fps(self, fps: float) -> None:
        self.max_fps = fps
        self._last_emit = 0.0

    async def wait_frame(self, previous: bytes | None = None) -> bytes | None:
        """Retired internal preview hook: never retain or emit a video frame."""
        return None

    @property
    def detection_version(self) -> int:
        """单调递增的检测消息版本，用于旁路订阅的 latest-only 对齐。"""
        return self._detection_version

    async def wait_detection(
        self, previous_version: int = 0, timeout: float | None = None
    ) -> tuple[int, FrameDetections | None]:
        """等待新检测结果或 YOLO 状态变化。

        返回当前版本和最新结果；超时返回原版本及当前结果。检测通道不读取或
        持有视频条件变量，因此即使视频播放端断开也能继续消费元数据。
        """
        async with self._detection_condition:
            predicate = lambda: self._closed or self._detection_version > previous_version or not self.yolo_enabled
            try:
                if timeout is None:
                    await self._detection_condition.wait_for(predicate)
                else:
                    await asyncio.wait_for(self._detection_condition.wait_for(predicate), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            return self._detection_version, self.latest_detections

    def try_subscribe(self) -> bool:
        return False

    def unsubscribe(self) -> None:
        self._active_subscribers = max(0, self._active_subscribers - 1)

    @property
    def active_subscribers(self) -> int:
        return self._active_subscribers

    async def _pull_loop(self):
        while not self._closed:
            loop = asyncio.get_running_loop()
            # OpenCV can release several buffered RTSP frames in one burst.
            # Eight frames absorb that jitter while retaining a hard bound.
            frames: asyncio.Queue = asyncio.Queue(maxsize=8)
            stop_reader = threading.Event()

            def offer(ok: bool, frame, error: str | None = None, dropped: int = 0) -> None:
                self.frames_dropped += dropped
                if frames.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        frames.get_nowait()
                    self.frames_dropped += 1
                frames.put_nowait((ok, frame, error))

            def read_source() -> None:
                capture = _open_video_capture(self.source_url)
                limiter = _FrameRateLimiter()
                pending_drops = 0
                try:
                    if not capture.isOpened():
                        loop.call_soon_threadsafe(
                            offer, False, None, f"cannot open source: {redact_source_url(self.source_url)}"
                        )
                        return
                    while not stop_reader.is_set():
                        ok, frame = capture.read()
                        if not ok:
                            loop.call_soon_threadsafe(
                                offer, False, None, "source read failed", pending_drops
                            )
                            return
                        now = time.monotonic()
                        current_fps = self.max_fps
                        if not limiter.allow(now, current_fps):
                            pending_drops += 1
                            continue
                        loop.call_soon_threadsafe(offer, True, frame, None, pending_drops)
                        pending_drops = 0
                except Exception as exc:
                    raw_source = str(self.source_url)
                    safe_source = redact_source_url(self.source_url) or "<source>"
                    loop.call_soon_threadsafe(
                        offer,
                        False,
                        None,
                        str(exc).replace(raw_source, safe_source),
                    )
                finally:
                    capture.release()

            reader_task = asyncio.create_task(asyncio.to_thread(read_source))
            try:
                while not self._closed:
                    ok, frame, error = await frames.get()
                    if not ok:
                        raise RuntimeError(error or f"cannot read source: {redact_source_url(self.source_url)}")
                    # Network cameras have normal arrival jitter. The public
                    # upload endpoint rejects bursts, but an internal RTSP pull
                    # must not tear down and reconnect because two frames arrive
                    # a few milliseconds closer than their nominal cadence.
                    await self.ingest_frame(
                        frame,
                        enforce_rate_limit=False,
                        pace_output=False,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                self._state = StreamState.ERROR
            finally:
                stop_reader.set()
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    await asyncio.wait_for(asyncio.shield(reader_task), timeout=2.0)
            if not self._closed:
                await asyncio.sleep(1)
