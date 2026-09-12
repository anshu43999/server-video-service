"""MediaMTX RTSP publisher used by each stream session.

The publisher owns one long-lived FFmpeg process per stream.  Frames are
encoded by :class:`H264Encoder` and written to the process stdin, so MediaMTX
can fan out the single encoded stream to WebRTC, LL-HLS and RTSP clients.
"""
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

import numpy as np

from .encoder import EncoderConfig, H264Encoder, EncoderUnavailableError


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
        self._encoder: H264Encoder | None = None
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

    def ffmpeg_command(self) -> list[str]:
        return [
            self.config.ffmpeg_path or "ffmpeg", "-loglevel", "error",
            "-f", "h264", "-i", "pipe:0", "-c:v", "copy", "-an",
            "-f", "rtsp", "-rtsp_transport", "tcp", self.url,
        ]

    def _ensure_encoder(self, frame: np.ndarray) -> H264Encoder:
        if self._encoder is None:
            h, w = frame.shape[:2]
            self._encoder = H264Encoder(EncoderConfig(w, h, fps=25.0), ffmpeg_path=self.config.ffmpeg_path)
        return self._encoder

    def _start_process(self) -> None:
        if self._process and self._process.poll() is None:
            return
        self._process = subprocess.Popen(
            self.ffmpeg_command(), stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        self.publish_state = "connected"
        self.last_error = None

    def _stop_process(self) -> None:
        process, self._process = self._process, None
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
        async with self._lock:
            try:
                payload = await asyncio.to_thread(self._ensure_encoder(frame).encode, frame)
            except (EncoderUnavailableError, ValueError) as exc:
                self.last_error = str(exc)
                self.publish_state = "failed"
                return False
            for attempt in range(self.config.max_reconnect_attempts + 1):
                if self._closed:
                    return False
                try:
                    self._start_process()
                    assert self._process and self._process.stdin
                    await asyncio.to_thread(self._process.stdin.write, payload)
                    await asyncio.to_thread(self._process.stdin.flush)
                    self.frames_published += 1
                    self.publish_state = "connected"
                    return True
                except (BrokenPipeError, OSError, AssertionError) as exc:
                    self.last_error = str(exc)
                    self.publish_state = "reconnecting" if attempt < self.config.max_reconnect_attempts else "failed"
                    self._stop_process()
                    if attempt < self.config.max_reconnect_attempts:
                        await asyncio.sleep(self.config.reconnect_delay)
            return False

    async def refresh_viewers(self) -> int:
        """Read MediaMTX path state when its control API is enabled."""
        if not self.config.api_url:
            return self.viewers
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
        return {
            "publish_state": self.publish_state,
            "viewers": self.viewers,
            "publish_path": self.path,
            "publish_url": self.url,
            "frames_published": self.frames_published,
            "publish_error": self.last_error,
        }


def _media_host(base_url: str) -> str:
    """Extract a credential-free host from the configured RTSP origin."""
    parsed = urlsplit(base_url)
    host = parsed.hostname or "127.0.0.1"
    # urlsplit.hostname omits brackets for IPv6 literals; retain valid URL
    # syntax when interpolating the host into HTTP origins.
    return f"[{host}]" if ":" in host and not host.startswith("[") else host
