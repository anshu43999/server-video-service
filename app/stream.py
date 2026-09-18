from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from dataclasses import dataclass, field

import cv2

from .config import settings
from .detection import FrameDetections
from .detector import YoloDetector, decode_image
from .overlay import draw_overlay
from .publisher import MediaMTXPublisher, PublisherConfig
from .protocol import InputRateLimitError, MAX_FRAME_BYTES, MAX_FRAME_HEIGHT, MAX_FRAME_WIDTH, StreamState
from .stream_config import redact_source_url


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
    _pending_preview_frame: object | None = field(default=None, init=False)
    _preview_task: asyncio.Task | None = field(default=None, init=False)
    _received_times: list[float] = field(default_factory=list, init=False)
    _processed_times: list[float] = field(default_factory=list, init=False)
    _output_times: list[float] = field(default_factory=list, init=False)
    _latencies: list[float] = field(default_factory=list, init=False)
    _last_frame_received_at: float | None = field(default=None, init=False)
    _last_captured_at_us: int = field(default=0, init=False)
    _state: StreamState = field(default=StreamState.CREATED, init=False)
    publisher: MediaMTXPublisher = field(init=False)
    model_catalog_id: str | None = field(default=None, init=False)
    model_scenario: str | None = field(default=None, init=False)
    model_purpose: str | None = field(default=None, init=False)
    alert_runtime: Any | None = None
    alert_error: str | None = None

    def __post_init__(self) -> None:
        self.publisher = MediaMTXPublisher(
            self.stream_id,
            PublisherConfig(
                enabled=settings.mediamtx_enabled,
                base_url=settings.mediamtx_rtsp_url,
                api_url=settings.mediamtx_api_url,
                ffmpeg_path=settings.mediamtx_ffmpeg_path,
                reconnect_delay=settings.mediamtx_reconnect_delay,
                max_reconnect_attempts=settings.mediamtx_max_reconnect_attempts,
                whep_base_url=settings.mediamtx_whep_url,
                llhls_base_url=settings.mediamtx_llhls_url,
                http_scheme=settings.mediamtx_http_scheme,
                fps=self.max_fps,
                encoder=settings.mediamtx_video_encoder,
            ),
        )

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
        self._state = StreamState.CLOSED
        # Wake output consumers before waiting for capture/encoder cleanup.  This
        # lets browsers tear down the old multipart response immediately while
        # the remaining session resources finish closing in the background.
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
        if self._preview_task:
            self._preview_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._preview_task
        await self.publisher.close()

    async def set_yolo(self, enabled: bool):
        self.yolo_enabled = enabled
        if enabled:
            self.detector._load()
        else:
            # YOLO 关闭时不保留检测结果：旁路通道按协议 §6.2 只发心跳。
            self.latest_detections = None
            if self._pending_frame is not None:
                self._pending_frame = None
        async with self._detection_condition:
            self._detection_condition.notify_all()

    def bind_model(self, *, model_id: str, model_path: str, scenario: str | None = None,
                   purpose: str | None = None, labels: list[str] | None = None,
                   imgsz: int | None = None, device: str | None = None) -> dict:
        """Switch only this stream to a validated registered model.

        A fresh detector is used so its lazy-loaded runtime and error state cannot
        leak into another stream (or retain the previously bound model).
        """
        previous = self.detector
        self.detector = YoloDetector(
            model_path,
            previous.confidence,
            int(imgsz or previous.imgsz),
            device or (previous.device or "auto"),
            labels or None,
            model_id=model_id,
        )
        self.model_catalog_id = model_id
        self.model_scenario = scenario
        self.model_purpose = purpose
        return self.model_metadata()

    def model_metadata(self) -> dict:
        metadata = self.detector.metadata()
        metadata.update({"catalog_model_id": self.model_catalog_id or metadata.get("model_id"),
                         "modelId": self.model_catalog_id or metadata.get("model_id"),
                         "scenario": self.model_scenario, "purpose": self.model_purpose})
        return metadata

    async def _publish_frame(self, frame, *, pace_output: bool = True) -> None:
        if pace_output:
            await self._wait_for_emit_slot()
        await self.publisher.publish(frame)
        await self.publisher.refresh_viewers()
        async with self._condition:
            self.last_error = None
            self._state = StreamState.OUTPUTTING
            emitted_at = time.monotonic()
            self._output_times.append(emitted_at)
            self._output_times = self._output_times[-60:]
            self.output_fps = self._window_fps(self._output_times)
        if self.latest_jpeg is None:
            # Preserve the existing ingest contract: the first frame is ready
            # when ingest_frame returns, even before a preview client connects.
            await self._encode_preview(frame)
        elif self.active_subscribers:
            self._pending_preview_frame = frame
            if self._preview_task is None or self._preview_task.done():
                self._preview_task = asyncio.create_task(self._preview_worker())

    async def _encode_preview(self, frame) -> None:
        ok, encoded = await asyncio.to_thread(
            cv2.imencode,
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), max(10, min(settings.jpeg_quality, 100))],
        )
        if not ok:
            raise ValueError("failed to encode processed frame")
        async with self._condition:
            self.latest_jpeg = encoded.tobytes()
            self._condition.notify_all()

    async def _preview_worker(self) -> None:
        """Encode only the newest browser-preview frame off the RTSP path."""
        while self._pending_preview_frame is not None and not self._closed:
            frame = self._pending_preview_frame
            self._pending_preview_frame = None
            await self._encode_preview(frame)

    async def _wait_for_emit_slot(self) -> None:
        """Pace output while the RTSP reader keeps only its latest frame."""
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
        result.update(self.publisher.metrics())
        return result

    async def _yolo_worker(self):
        while not self._closed:
            pending = self._pending_frame
            self._pending_frame = None
            if pending is None:
                return
            frame, frame_seq, captured_at_us = pending
            try:
                detector = self.detector
                if detector.load_error:
                    processed = frame
                    self.frames_fallback += 1
                else:
                    result = await asyncio.to_thread(detector.infer, frame)
                    # A model switch may happen while inference is in flight.
                    # Drop the stale result rather than publishing it as if it
                    # came from the newly bound model.
                    if detector is not self.detector:
                        continue
                    # 推理可能跨越 YOLO 开关变更；关闭后丢弃在途结果，避免旁路
                    # 在心跳模式下短暂发布过期检测消息。
                    if not self.yolo_enabled:
                        processed = frame
                    elif result.fallback_reason:
                        processed = frame
                        self.frames_fallback += 1
                    else:
                        self.latest_detections = FrameDetections(
                            self.stream_id, frame_seq, captured_at_us, result
                        )
                        async with self._detection_condition:
                            self._detection_version += 1
                            self._detection_condition.notify_all()
                        # 叠加是结构化结果的下游，可关闭；关闭时输出原始帧。
                        processed = (
                            draw_overlay(frame, result.detections) if self.overlay_enabled else frame
                        )
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
                if self.alert_runtime is not None and not detector.load_error and not result.fallback_reason:
                    try:
                        self.alert_runtime.process(
                            source_id=self.stream_id,
                            captured_at_us=captured_at_us,
                            result=result,
                            frame=processed,
                        )
                        self.alert_error = None
                    except Exception as exc:
                        # Persistence and delivery failures must not take down video.
                        self.alert_error = str(exc)[:500]
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
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
        self._received_times.append(now)
        self._received_times = self._received_times[-60:]
        if self.yolo_enabled:
            if self._pending_frame is not None:
                self.frames_dropped += 1
            self._pending_frame = (frame, self.frame_seq, captured_at_us)
            if self._processing_task is None or self._processing_task.done():
                self._processing_task = asyncio.create_task(self._yolo_worker())
            return
        await self._publish_frame(frame, pace_output=pace_output)

    async def set_max_fps(self, fps: float) -> None:
        self.max_fps = fps
        self._last_emit = 0.0
        await self.publisher.set_fps(fps)

    async def wait_frame(self, previous: bytes | None = None) -> bytes | None:
        async with self._condition:
            # Compare object identity: two consecutive frames may encode to identical bytes.
            await self._condition.wait_for(lambda: self._closed or self.latest_jpeg is not previous)
            # A closed session must terminate every MJPEG/WebSocket consumer.  Returning
            # the retained last frame here makes a consumer spin without waiting and
            # repeatedly send that stale frame after the browser has disconnected.
            if self._closed:
                return None
            return self.latest_jpeg

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
