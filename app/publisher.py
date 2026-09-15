"""Persistent FFmpeg H.264 publisher used by each stream session."""
from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import cv2
import numpy as np

from .encoder import EncoderConfig


@dataclass
class PublisherConfig:
    enabled: bool = False
    base_url: str = "rtsp://127.0.0.1:8554"
    ffmpeg_path: str | None = None
    reconnect_delay: float = 1.0
    max_reconnect_attempts: int = 3
    api_url: str | None = None
    whep_base_url: str | None = None
    llhls_base_url: str | None = None
    http_scheme: str = "http"
    fps: float = 20.0
    bitrate: str = "6000k"
    preset: str = "ultrafast"
    encoder: str = "auto"

    def __post_init__(self) -> None:
        if self.encoder not in {"auto", "h264_qsv", "libx264"}:
            raise ValueError("encoder must be auto, h264_qsv, or libx264")


class MediaMTXPublisher:
    """Low-latency publisher with bounded automatic reconnects."""

    def __init__(self, stream_id: str, config: PublisherConfig | None = None) -> None:
        self.stream_id = stream_id
        self.config = config or PublisherConfig()
        self.path = stream_id
        self.publish_state = "idle"
        self.viewers = 0
        self.last_error: str | None = None
        self.frames_published = 0
        self._process: subprocess.Popen[bytes] | None = None
        self._frame_size: tuple[int, int] | None = None
        self._published_times: list[float] = []
        self.encode_ms: float | None = None
        self._last_viewer_refresh = 0.0
        self._encoder_candidates = (
            ["h264_qsv", "libx264"] if self.config.encoder == "auto" else [self.config.encoder]
        )
        self._encoder_index = 0
        self._process_frames = 0
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/{self.path}"

    def playback(self) -> dict[str, Any]:
        """Return protocol URLs and current availability for this stream.

        MediaMTX exposes all three protocols from the same published path. We
        report addresses even before the first frame so clients can cache the
        endpoint, while availability reflects the live publisher state.
        """
        host = _media_host(self.config.base_url)
        whep_base = self.config.whep_base_url or f"{self.config.http_scheme}://{host}:8889"
        llhls_base = self.config.llhls_base_url or f"{self.config.http_scheme}://{host}:8888"
        available = bool(self.config.enabled and self.publish_state == "connected")
        return {
            "publish_state": self.publish_state,
            "whep": {"url": f"{whep_base.rstrip('/')}/{self.path}/whep", "available": available},
            "llhls": {"url": f"{llhls_base.rstrip('/')}/{self.path}/index.m3u8", "available": available},
            "rtsp": {
                "url": self.url,
                "available": available,
                "diagnostics_only": True,
            },
        }

    @property
    def active_encoder(self) -> str:
        return self._encoder_candidates[self._encoder_index]

    def ffmpeg_command(self, width: int, height: int, encoder_name: str | None = None) -> list[str]:
        encoder = EncoderConfig(
            width,
            height,
            fps=self.config.fps,
            bitrate=self.config.bitrate,
        )
        command = [
            self.config.ffmpeg_path or "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "yuv420p",
            "-video_size", f"{width}x{height}",
            "-framerate", str(encoder.fps), "-i", "pipe:0",
            "-an",
        ]
        selected = encoder_name or self.active_encoder
        if selected == "h264_qsv":
            command += [
                "-vf", "format=nv12", "-c:v", "h264_qsv", "-preset", "veryfast",
                "-profile:v", encoder.profile, "-level:v", encoder.level,
            ]
        else:
            command += [
                "-c:v", "libx264", "-preset", self.config.preset,
                "-tune", encoder.tune, "-pix_fmt", "yuv420p",
                "-profile:v", encoder.profile, "-level:v", encoder.level,
            ]
        command += [
            "-bf", "0", "-g", str(encoder.gop_frames),
            "-keyint_min", str(encoder.gop_frames),
            "-b:v", encoder.bitrate, "-maxrate", encoder.bitrate,
            "-bufsize", encoder.bitrate,
            "-f", "rtsp", "-rtsp_transport", "tcp", "-flush_packets", "1", self.url,
        ]
        return command

    def _start_process(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        frame_size = (width, height)
        if self._process and self._process.poll() is None and self._frame_size == frame_size:
            return
        self._stop_process()
        self._process = subprocess.Popen(
            self.ffmpeg_command(width, height), stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._frame_size = frame_size
        self._process_frames = 0
        self.publish_state = "starting"
        self.last_error = None

    def _stop_process(self) -> None:
        process, self._process = self._process, None
        self._frame_size = None
        if process is None:
            return
        with contextlib.suppress(Exception):
            if process.stdin:
                process.stdin.close()
        with contextlib.suppress(Exception):
            process.terminate()
            process.wait(timeout=1)
        with contextlib.suppress(Exception):
            process.kill()

    async def publish(self, frame: np.ndarray) -> bool:
        if self._closed or not self.config.enabled:
            return False
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be a HxWx3 BGR numpy array")
        async with self._lock:
            for attempt in range(self.config.max_reconnect_attempts + 1):
                if self._closed:
                    return False
                try:
                    self._start_process(frame)
                    assert self._process and self._process.stdin
                    started = time.perf_counter()
                    # YUV420P halves the Windows pipe bandwidth compared with
                    # BGR24 and is already the encoder's native 4:2:0 layout.
                    payload = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
                    written = await asyncio.to_thread(self._process.stdin.write, payload)
                    await asyncio.to_thread(self._process.stdin.flush)
                    if written is not None and written != payload.nbytes:
                        raise BrokenPipeError(f"short FFmpeg stdin write: {written}/{payload.nbytes}")
                    self.encode_ms = round((time.perf_counter() - started) * 1000, 3)
                    self.frames_published += 1
                    self._process_frames += 1
                    now = time.monotonic()
                    self._published_times = (self._published_times + [now])[-60:]
                    self.publish_state = "connected"
                    return True
                except (BrokenPipeError, OSError, AssertionError) as exc:
                    self.last_error = str(exc)
                    self.publish_state = "reconnecting" if attempt < self.config.max_reconnect_attempts else "failed"
                    if self.config.encoder == "auto" and self._process_frames < 3:
                        self._encoder_index = min(self._encoder_index + 1, len(self._encoder_candidates) - 1)
                    self._stop_process()
                    if attempt < self.config.max_reconnect_attempts:
                        await asyncio.sleep(self.config.reconnect_delay)
            return False

    async def set_fps(self, fps: float) -> None:
        """Apply a new constant output rate on the next published frame."""
        async with self._lock:
            if self.config.fps == fps:
                return
            self.config.fps = fps
            self._stop_process()
            self.publish_state = "idle"

    async def refresh_viewers(self) -> int:
        """Read MediaMTX path state when its control API is enabled."""
        if not self.config.api_url:
            return self.viewers
        now = time.monotonic()
        if now - self._last_viewer_refresh < 1.0:
            return self.viewers
        self._last_viewer_refresh = now
        url = self.config.api_url.rstrip("/") + "/v3/paths/list"
        try:
            def read() -> dict[str, Any]:
                with urllib.request.urlopen(url, timeout=1.5) as response:
                    return json.loads(response.read().decode("utf-8"))
            data = await asyncio.to_thread(read)
            for item in data.get("items", []):
                if item.get("name") == self.path:
                    self.viewers = int(item.get("readers", item.get("readersCount", 0)) or 0)
                    break
            else:
                self.viewers = 0
        except Exception:
            # The API is optional in the stock MediaMTX configuration.
            self.viewers = 0
        return self.viewers

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            self._stop_process()
        self.publish_state = "idle"

    def metrics(self) -> dict[str, Any]:
        encode_fps = 0.0
        if len(self._published_times) > 1:
            elapsed = self._published_times[-1] - self._published_times[0]
            encode_fps = round((len(self._published_times) - 1) / elapsed, 2) if elapsed > 0 else 0.0
        return {
            "publish_state": self.publish_state,
            "viewers": self.viewers,
            "publish_path": self.path,
            "publish_url": self.url,
            "frames_published": self.frames_published,
            "publish_error": self.last_error,
            "encoder_backend": f"ffmpeg-persistent:{self.active_encoder}",
            "encoder_frames": self.frames_published,
            "encoder_fps": encode_fps,
            "encoder_last_ms": self.encode_ms,
        }


def _media_host(base_url: str) -> str:
    """Extract a credential-free host from the configured RTSP origin."""
    parsed = urlsplit(base_url)
    host = parsed.hostname or "127.0.0.1"
    # urlsplit.hostname omits brackets for IPv6 literals; retain valid URL
    # syntax when interpolating the host into HTTP origins.
    return f"[{host}]" if ":" in host and not host.startswith("[") else host
