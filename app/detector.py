from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import cv2

from .detection import CAPABILITY_BOX, CAPABILITY_TRACK, Detection, InferenceResult, NormalizedBox

LOGGER = logging.getLogger(__name__)


def _to_list(value: Any) -> list:
    """张量或数组转 list；纯 Python 序列原样返回，便于测试用普通嵌套 list 驱动。"""
    if value is None:
        return []
    to_list = getattr(value, "tolist", None)
    if callable(to_list):
        converted = to_list()
        return converted if isinstance(converted, list) else [converted]
    return list(value)


def derive_provides(detections: tuple[Detection, ...]) -> tuple[str, ...]:
    """按实际载荷申报能力（Schema 要求 provides 与载荷一致）。

    检测型权重恒有 BOX：没检出目标的空帧也必须申报 BOX，
    否则 ABSENCE 一类规则会因为能力不满足被拒。TRACK 只在真的带跟踪 id 时申报。
    """
    provides = [CAPABILITY_BOX]
    if any(item.track_id is not None for item in detections):
        provides.append(CAPABILITY_TRACK)
    return tuple(provides)


def resolve_label(class_id: int, class_names: tuple[str, ...]) -> str:
    """类别 id 转标签；越界或缺名时退化成 id 字符串，不猜业务名。"""
    if 0 <= class_id < len(class_names):
        name = str(class_names[class_id]).strip()
        if name:
            return name
    return str(class_id)


def build_detections(
    raw_result: Any, frame_width: int, frame_height: int, class_names: tuple[str, ...] = ()
) -> tuple[Detection, ...]:
    """把一个推理结果对象转成结构化检测。

    只按属性取值（xyxy / conf / cls / id），不依赖 ultralytics 的类型，
    因此可用桩对象测试坐标归一化与退化框丢弃。
    """
    boxes = getattr(raw_result, "boxes", None)
    if boxes is None:
        return ()
    coords = _to_list(getattr(boxes, "xyxy", None))
    confidences = _to_list(getattr(boxes, "conf", None))
    class_ids = _to_list(getattr(boxes, "cls", None))
    track_ids = _to_list(getattr(boxes, "id", None))
    detections: list[Detection] = []
    for index, corners in enumerate(coords):
        if len(corners) < 4:
            continue
        box = NormalizedBox.from_pixel_box(
            float(corners[0]), float(corners[1]), float(corners[2]), float(corners[3]), frame_width, frame_height
        )
        if box is None:
            continue  # 退化框（宽或高归一化后为 0）直接丢弃，不进结构化结果
        class_id = int(class_ids[index]) if index < len(class_ids) else 0
        confidence = float(confidences[index]) if index < len(confidences) else 0.0
        track_id = None
        if index < len(track_ids) and track_ids[index] is not None:
            track_id = str(int(track_ids[index]))
        detections.append(
            Detection(
                class_id=class_id,
                label=resolve_label(class_id, class_names),
                confidence=min(max(confidence, 0.0), 1.0),
                box=box,
                track_id=track_id,
            )
        )
    return tuple(detections)


class YoloDetector:
    """Lazy YOLO adapter. Importing the service does not require ultralytics."""

    def __init__(self, model_path: str, confidence: float = 0.25, imgsz: int = 640, device: str = "auto", classes: list[str] | None = None, model_id: str | None = None):
        self.model_path = model_path
        self._catalog_model_id = model_id
        self.confidence = confidence
        self.imgsz = imgsz
        self.device = None if device in ("", "auto") else device
        self.classes = classes
        self._model: Any | None = None
        self._load_error: str | None = None
        self._last_provides: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self._model is not None or self._load_error is None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def model_id(self) -> str:
        """市场模型标识；未登记的权重退化为文件 stem。"""
        return self._catalog_model_id or Path(self.model_path).stem

    @property
    def class_names(self) -> tuple[str, ...]:
        if self.classes:
            return tuple(str(item) for item in self.classes)
        raw_names = getattr(self._model, "names", None) if self._model is not None else None
        if isinstance(raw_names, dict):
            return tuple(str(raw_names[key]) for key in sorted(raw_names))
        if isinstance(raw_names, (list, tuple)):
            return tuple(str(item) for item in raw_names)
        return ()

    def _load(self) -> None:
        if self._model is not None or self._load_error is not None:
            return
        try:
            from ultralytics import YOLO  # type: ignore

            if not Path(self.model_path).exists():
                raise FileNotFoundError(f"YOLO model not found: {self.model_path}")
            self._model = YOLO(self.model_path)
        except Exception as exc:  # keep video available even when model setup fails
            self._load_error = str(exc)
            LOGGER.warning("YOLO unavailable: %s", exc)

    def infer(self, frame) -> InferenceResult:
        """结构化推理：返回类别、置信度与归一化坐标，不画任何东西。"""
        height, width = frame.shape[:2]
        self._load()
        if self._model is None:
            self._last_provides = ()
            return InferenceResult.unavailable(self._load_error or "model not loaded", width, height)
        kwargs: dict[str, Any] = {"conf": self.confidence, "imgsz": self.imgsz, "verbose": False}
        if self.device is not None:
            kwargs["device"] = self.device
        started_at = time.perf_counter()
        results = self._model.predict(frame, **kwargs)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        class_names = self.class_names
        detections = build_detections(results[0], width, height, class_names) if results else ()
        provides = derive_provides(detections)
        self._last_provides = provides
        return InferenceResult(
            detections=detections,
            model_id=self.model_id,
            class_names=class_names,
            frame_width=width,
            frame_height=height,
            inference_ms=round(elapsed_ms, 3),
            provides=provides,
        )

    def metadata(self) -> dict[str, Any]:
        path = Path(self.model_path)
        return {
            "model_path": self.model_path,
            "model_id": self.model_id,
            "model_exists": path.exists(),
            "model_size_bytes": path.stat().st_size if path.exists() else None,
            "confidence": self.confidence,
            "imgsz": self.imgsz,
            "device": self.device or "auto",
            "classes": list(self.class_names),
            "loaded": self._model is not None,
            "load_error": self._load_error,
            # 上一帧实际推导出的能力；没推理过时为空，不预先承诺。
            "provides": list(self._last_provides),
        }


def decode_image(payload: bytes):
    import numpy as np

    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("payload is not a valid JPEG/PNG image")
    return image
