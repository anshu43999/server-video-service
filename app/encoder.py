"""Low-latency H.264 encoding primitives.

The encoder is intentionally independent from :mod:`app.stream` so the media
publishing task can attach it without coupling frame ingestion to a particular
codec implementation.  FFmpeg is preferred when available; PyAV is used when
installed and FFmpeg is unavailable.  Both backends expose the same small API
and record encode timing/FPS metrics.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np


class EncoderUnavailableError(RuntimeError):
    """Raised when no supported H.264 encoder can be initialized."""


@dataclass(frozen=True)
class EncoderConfig:
    width: int
    height: int
    fps: float = 25.0
    profile: str = "baseline"
    level: str = "4.0"
    bitrate: str = "2500k"
    gop_seconds: float = 2.0
    tune: str = "zerolatency"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.profile.lower() not in {"baseline", "main"}:
            raise ValueError("profile must be Baseline or Main")
        try:
            if float(self.level) > 4.0:
                raise ValueError("H.264 level must be <= 4.0")
        except ValueError:
            raise ValueError("level must be a numeric H.264 level")
        if not 1.0 <= self.gop_seconds <= 2.0:
            raise ValueError("gop_seconds must be between 1 and 2 seconds")
        if self.tune != "zerolatency":
            raise ValueError("tune must be zerolatency")

    @property
    def gop_frames(self) -> int:
        return max(1, round(self.fps * self.gop_seconds))


@dataclass
class EncoderMetrics:
    frames_encoded: int = 0
    last_encode_ms: float | None = None
    encode_fps: float = 0.0
    backend: str = "unknown"
    _times: list[float] = field(default_factory=list, repr=False)

    def observe(self, elapsed_ms: float) -> None:
        now = time.monotonic()
        self.frames_encoded += 1
        self.last_encode_ms = round(elapsed_ms, 3)
        self._times = (self._times + [now])[-60:]
        if len(self._times) > 1:
            span = self._times[-1] - self._times[0]
            self.encode_fps = round((len(self._times) - 1) / span, 2) if span > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "encoder_backend": self.backend,
            "encoder_frames": self.frames_encoded,
            "encoder_fps": self.encode_fps,
            "encoder_last_ms": self.last_encode_ms,
        }


class H264Encoder:
    """Encode BGR numpy frames to Annex-B H.264 access units."""

    def __init__(
        self,
        config: EncoderConfig,
        *,
        backend: str = "auto",
        ffmpeg_path: str | None = None,
    ) -> None:
        self.config = config
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self.backend = self._select_backend(backend)
        self.metrics = EncoderMetrics(backend=self.backend)

    @staticmethod
    def pyav_available() -> bool:
        return importlib.util.find_spec("av") is not None

    def _select_backend(self, requested: str) -> str:
        requested = requested.lower()
        if requested not in {"auto", "ffmpeg", "pyav"}:
            raise ValueError("backend must be auto, ffmpeg, or pyav")
        if requested == "ffmpeg":
            if not self.ffmpeg_path:
                raise EncoderUnavailableError("FFmpeg executable not found")
            return "ffmpeg"
        if requested == "pyav":
            if not self.pyav_available():
                raise EncoderUnavailableError("PyAV is not installed")
            return "pyav"
        if self.ffmpeg_path:
            return "ffmpeg"
        if self.pyav_available():
            return "pyav"
        raise EncoderUnavailableError("neither FFmpeg nor PyAV is available")

    def ffmpeg_command(self) -> list[str]:
        c = self.config
        return [
            self.ffmpeg_path or "ffmpeg",
            "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s:v", f"{c.width}x{c.height}", "-r", str(c.fps), "-i", "pipe:0",
            "-frames:v", "1", "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", c.profile.lower(), "-level:v", c.level,
            "-bf", "0", "-g", str(c.gop_frames), "-keyint_min", str(c.gop_frames),
            "-tune", c.tune, "-b:v", c.bitrate, "-f", "h264", "pipe:1",
        ]

    def encode(self, frame: np.ndarray) -> bytes:
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be a HxWx3 BGR numpy array")
        if frame.shape[1] != self.config.width or frame.shape[0] != self.config.height:
            raise ValueError("frame dimensions do not match encoder config")
        started = time.perf_counter()
        if self.backend == "ffmpeg":
            output = self._encode_ffmpeg(frame)
        else:
            output = self._encode_pyav(frame)
        self.metrics.observe((time.perf_counter() - started) * 1000)
        return output

    def _encode_ffmpeg(self, frame: np.ndarray) -> bytes:
        proc = subprocess.run(
            self.ffmpeg_command(), input=np.ascontiguousarray(frame).tobytes(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            detail = proc.stderr.decode("utf-8", errors="replace").strip()
            raise EncoderUnavailableError(detail or "FFmpeg H.264 encoding failed")
        return proc.stdout

    def _encode_pyav(self, frame: np.ndarray) -> bytes:
        try:
            import av  # type: ignore

            ctx = av.CodecContext.create("libx264", "w")
            ctx.width, ctx.height = self.config.width, self.config.height
            ctx.pix_fmt = "yuv420p"
            ctx.time_base = (1, int(round(self.config.fps)))
            ctx.framerate = (int(round(self.config.fps)), 1)
            ctx.options = {
                "profile": self.config.profile.lower(), "level": self.config.level,
                "bf": "0", "g": str(self.config.gop_frames), "keyint_min": str(self.config.gop_frames),
                "tune": self.config.tune, "b": self.config.bitrate,
            }
            ctx.open()
            packets = ctx.encode(av.VideoFrame.from_ndarray(frame, format="bgr24"))
            packets += ctx.encode(None)
            return b"".join(bytes(packet) for packet in packets)
        except Exception as exc:
            raise EncoderUnavailableError(f"PyAV H.264 encoding failed: {exc}") from exc
