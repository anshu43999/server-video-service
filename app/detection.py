"""结构化检测结果的值对象（M08-T01）。

只用标准库。推理层、检测旁路（docs/video-protocol.md §6.2）与告警观测信封
（docs/alert-engine-spec.md §4）都从这里取同一份结构，避免三处各定义一套框。

本模块不含任何业务类别名：标签一律来自权重自带类名或模型 Manifest。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

# 与 docs/alert-engine.schema.json 的 Capability 枚举同名（本模块只涉及其中三项）。
CAPABILITY_BOX = "BOX"
CAPABILITY_TRACK = "TRACK"
CAPABILITY_MASK = "MASK"

# 归一化坐标容差：越界不超过它按夹紧处理，超出则整框丢弃。
COORD_TOLERANCE = 1e-6

# 告警引擎 sourceId 的字符集与长度（Schema SourceId 同一条正则）。
SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def iso8601_from_us(captured_at_us: int) -> str:
    """微秒时间戳转带时区偏移的 ISO8601（§6.2 的 captured_at）。"""
    moment = datetime.fromtimestamp(captured_at_us / 1_000_000, tz=timezone.utc).astimezone()
    return moment.isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class NormalizedBox:
    """归一化框：左上原点，x/y 为左上角，要求 x+w ≤ 1、y+h ≤ 1。"""

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "w", "h"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"box.{name} must be a finite number, got {value!r}")
        if self.w <= 0 or self.h <= 0:
            raise ValueError(f"box must have positive size, got w={self.w} h={self.h}")
        if self.x < 0 or self.y < 0:
            raise ValueError(f"box origin must be inside the frame, got x={self.x} y={self.y}")
        if self.x + self.w > 1 + COORD_TOLERANCE or self.y + self.h > 1 + COORD_TOLERANCE:
            raise ValueError("box must satisfy x+w <= 1 and y+h <= 1")

    @classmethod
    def from_pixel_box(
        cls, x1: float, y1: float, x2: float, y2: float, frame_width: int, frame_height: int
    ) -> "NormalizedBox | None":
        """像素 xyxy 转归一化框；越界夹紧，退化（宽或高为 0）返回 None 由调用方跳过。"""
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError(f"frame size must be positive, got {frame_width}x{frame_height}")
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        nx = min(max(left / frame_width, 0.0), 1.0)
        ny = min(max(top / frame_height, 0.0), 1.0)
        nw = min(max(right / frame_width, 0.0), 1.0) - nx
        nh = min(max(bottom / frame_height, 0.0), 1.0) - ny
        if round(nw, 6) <= 0 or round(nh, 6) <= 0:
            return None
        return cls(round(nx, 6), round(ny, 6), round(nw, 6), round(nh, 6))

    def to_wire(self) -> dict:
        return {"x": round(self.x, 6), "y": round(self.y, 6), "w": round(self.w, 6), "h": round(self.h, 6)}

    def as_pixels(self, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        """回到像素 xyxy，供叠加层画框。"""
        return (
            int(round(self.x * frame_width)),
            int(round(self.y * frame_height)),
            int(round((self.x + self.w) * frame_width)),
            int(round((self.y + self.h) * frame_height)),
        )


@dataclass(frozen=True)
class Detection:
    """一个检测目标。label 是权重原始类名，中文显示名由 Manifest 映射层负责。"""

    class_id: int
    label: str
    confidence: float
    box: NormalizedBox | None = None
    track_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.class_id, int) or self.class_id < 0:
            raise ValueError(f"class_id must be a non-negative int, got {self.class_id!r}")
        if not self.label:
            raise ValueError("label must not be empty")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be within [0, 1], got {self.confidence!r}")
        if self.track_id is not None and not SOURCE_ID_PATTERN.match(self.track_id):
            raise ValueError(f"track_id must match {SOURCE_ID_PATTERN.pattern}, got {self.track_id!r}")

    def to_wire(self) -> dict:
        """docs/video-protocol.md §6.2 的 detections 元素。"""
        payload: dict = {
            "class_id": self.class_id,
            "class_name": self.label,
            "confidence": round(self.confidence, 4),
        }
        if self.box is not None:
            payload["box"] = self.box.to_wire()
        if self.track_id is not None:
            payload["track_id"] = self.track_id
        return payload

    def to_alert_detection(self) -> dict:
        """docs/alert-engine.schema.json 的 Detection（additionalProperties: false）。"""
        payload: dict = {"label": self.label, "confidence": round(self.confidence, 6)}
        if self.box is not None:
            payload["box"] = self.box.to_wire()
        if self.track_id is not None:
            payload["trackId"] = self.track_id
        return payload


@dataclass(frozen=True)
class InferenceResult:
    """一帧推理的全部结构化产出。叠加图像不在其中：叠加由本结果推导。"""

    detections: tuple[Detection, ...] = ()
    model_id: str = ""
    class_names: tuple[str, ...] = ()
    frame_width: int = 0
    frame_height: int = 0
    inference_ms: float = 0.0
    provides: tuple[str, ...] = ()
    fallback_reason: str | None = None

    @classmethod
    def unavailable(cls, reason: str, frame_width: int = 0, frame_height: int = 0) -> "InferenceResult":
        """模型不可用：返回空检测并带上原因，调用方据此走原始帧回退。"""
        return cls(frame_width=frame_width, frame_height=frame_height, fallback_reason=reason)

    @property
    def detection_count(self) -> int:
        return len(self.detections)

    @property
    def has_tracking(self) -> bool:
        return any(item.track_id is not None for item in self.detections)


@dataclass(frozen=True)
class FrameDetections:
    """把一帧的身份（帧序号与采集时间）和推理结果绑在一起。"""

    stream_id: str
    frame_seq: int
    captured_at_us: int
    result: InferenceResult

    def to_wire(self) -> dict:
        """docs/video-protocol.md §6.2 的整条检测消息。"""
        return {
            "stream_id": self.stream_id,
            "frame_seq": self.frame_seq,
            "captured_at": iso8601_from_us(self.captured_at_us),
            "model": self.result.model_id,
            "inference_ms": round(self.result.inference_ms, 2),
            "detections": [item.to_wire() for item in self.result.detections],
        }

    def to_observation(self, source_id: str | None = None) -> dict:
        """docs/alert-engine-spec.md §4 的观测信封。

        载荷可以为空：空信封必须照样送入引擎（推进 ABSENCE 计时与未处置提级）。
        引擎侧的校验、时间单调断言与显式拒绝属于 M11-T03，本函数只做映射。
        """
        resolved = source_id or self.stream_id
        if not SOURCE_ID_PATTERN.match(resolved):
            raise ValueError(
                f"sourceId must match {SOURCE_ID_PATTERN.pattern}, got {resolved!r}; "
                "pass source_id= to map long or non-ASCII stream ids"
            )
        envelope: dict = {
            "sourceId": resolved,
            "frameSeq": self.frame_seq,
            "capturedAtUs": self.captured_at_us,
            "provides": list(self.result.provides),
            "detections": [item.to_alert_detection() for item in self.result.detections],
        }
        if self.result.frame_width > 0 and self.result.frame_height > 0:
            envelope["frameWidth"] = self.result.frame_width
            envelope["frameHeight"] = self.result.frame_height
        if self.result.model_id:
            envelope["model"] = {"modelId": self.result.model_id, "classNames": list(self.result.class_names)}
        return envelope
