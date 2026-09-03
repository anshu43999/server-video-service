from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Any

import cv2

LOGGER = logging.getLogger(__name__)


class YoloDetector:
    """Lazy YOLO adapter. Importing the service does not require ultralytics."""

    def __init__(self, model_path: str, confidence: float = 0.25, imgsz: int = 640, device: str = "auto", classes: list[str] | None = None):
        self.model_path = model_path
        self.confidence = confidence
        self.imgsz = imgsz
        self.device = None if device in ("", "auto") else device
        self.classes = classes
        self._model: Any | None = None
        self._load_error: str | None = None

    @property
    def available(self) -> bool:
        return self._model is not None or self._load_error is None

    @property
    def load_error(self) -> str | None:
        return self._load_error

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

    def annotate(self, frame):
        self._load()
        if self._model is None:
            return frame
        kwargs = {"conf": self.confidence, "imgsz": self.imgsz, "verbose": False}
        if self.device is not None:
            kwargs["device"] = self.device
        results = self._model.predict(frame, **kwargs)
        if not results:
            return frame
        return results[0].plot()

    def metadata(self) -> dict[str, Any]:
        path = Path(self.model_path)
        names = self.classes
        if names is None and self._model is not None:
            raw_names = getattr(self._model, "names", None)
            if isinstance(raw_names, dict):
                names = [str(raw_names[key]) for key in sorted(raw_names)]
            elif isinstance(raw_names, list):
                names = [str(item) for item in raw_names]
        return {
            "model_path": self.model_path,
            "model_exists": path.exists(),
            "model_size_bytes": path.stat().st_size if path.exists() else None,
            "confidence": self.confidence,
            "imgsz": self.imgsz,
            "device": self.device or "auto",
            "classes": names or [],
            "loaded": self._model is not None,
            "load_error": self._load_error,
        }


def decode_image(payload: bytes):
    import numpy as np

    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("payload is not a valid JPEG/PNG image")
    return image
