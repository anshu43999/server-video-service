"""Unified observation envelopes for the alert engine (M11-T03).

The alert engine deliberately consumes one small, JSON-compatible envelope.  This
module is the boundary between inference adapters and the pure rule evaluator:
it validates identity/time, normalises the four payload families and provides
explicit capability/rejection information instead of silently dropping input.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
CAPABILITIES = frozenset({"BOX", "TRACK", "MASK", "SCALAR", "POLYGON_ROI", "LINE_ROI"})


class ObservationError(ValueError):
    """Malformed observation or an invalid source time sequence."""


class NonMonotonicTimestampError(ObservationError):
    """A source submitted an observation older than its last accepted one."""

    def __init__(self, source_id: str, previous_us: int, received_us: int) -> None:
        super().__init__(
            f"capturedAtUs must be monotonic for source {source_id!r}: "
            f"{received_us} < {previous_us}"
        )
        self.source_id, self.previous_us, self.received_us = source_id, previous_us, received_us


@dataclass(frozen=True, slots=True)
class Classification:
    label: str
    confidence: float

    def __post_init__(self) -> None:
        _label(self.label, "classification.label")
        _confidence(self.confidence, "classification.confidence")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Classification":
        return cls(str(value.get("label", "")), float(value.get("confidence", -1)))

    def to_mapping(self) -> dict[str, Any]:
        return {"label": self.label, "confidence": round(self.confidence, 6)}


@dataclass(frozen=True, slots=True)
class Mask:
    label: str
    confidence: float
    area_ratio: float
    polygon: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        _label(self.label, "mask.label")
        _confidence(self.confidence, "mask.confidence")
        if not isinstance(self.area_ratio, (int, float)) or not math.isfinite(self.area_ratio) or not 0 <= self.area_ratio <= 1:
            raise ObservationError(f"mask.areaRatio must be within [0, 1], got {self.area_ratio!r}")
        points = []
        for raw in self.polygon:
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 2:
                raise ObservationError(f"mask.polygon point must be [x, y], got {raw!r}")
            point = (float(raw[0]), float(raw[1]))
            if not all(math.isfinite(c) and 0 <= c <= 1 for c in point):
                raise ObservationError(f"mask.polygon point must be normalized, got {point!r}")
            points.append(point)
        object.__setattr__(self, "polygon", tuple(points))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Mask":
        return cls(
            str(value.get("label", "")), float(value.get("confidence", -1)),
            float(value.get("areaRatio", value.get("area_ratio", -1))),
            tuple(tuple(p) for p in value.get("polygon", ())),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": self.label, "confidence": round(self.confidence, 6),
            "areaRatio": round(self.area_ratio, 6),
        }
        if self.polygon:
            payload["polygon"] = [[round(x, 6), round(y, 6)] for x, y in self.polygon]
        return payload


@dataclass(frozen=True, slots=True)
class Scalar:
    metric_id: str
    value: float
    unit: str | None = None

    def __post_init__(self) -> None:
        if not SOURCE_ID_PATTERN.match(self.metric_id):
            raise ObservationError(f"scalar.metricId must match {SOURCE_ID_PATTERN.pattern}")
        if not isinstance(self.value, (int, float)) or not math.isfinite(self.value):
            raise ObservationError(f"scalar.value must be finite, got {self.value!r}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Scalar":
        return cls(str(value.get("metricId", value.get("metric_id", ""))), float(value.get("value", float("nan"))), value.get("unit"))

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"metricId": self.metric_id, "value": self.value}
        if self.unit is not None:
            payload["unit"] = self.unit
        return payload


@dataclass(frozen=True, slots=True)
class ObservationEnvelope:
    source_id: str
    frame_seq: int
    captured_at_us: int
    provides: tuple[str, ...] = ()
    detections: tuple[Mapping[str, Any], ...] = ()
    classifications: tuple[Classification, ...] = ()
    masks: tuple[Mask, ...] = ()
    scalars: tuple[Scalar, ...] = ()
    frame_width: int | None = None
    frame_height: int | None = None
    model: Mapping[str, Any] | None = None
    lost_track_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not SOURCE_ID_PATTERN.match(self.source_id):
            raise ObservationError(f"sourceId must match {SOURCE_ID_PATTERN.pattern}, got {self.source_id!r}")
        if not isinstance(self.frame_seq, int) or isinstance(self.frame_seq, bool) or self.frame_seq < 0:
            raise ObservationError("frameSeq must be a non-negative integer")
        if not isinstance(self.captured_at_us, int) or isinstance(self.captured_at_us, bool) or self.captured_at_us < 0:
            raise ObservationError("capturedAtUs must be a non-negative integer (microseconds)")
        caps = tuple(dict.fromkeys(self.provides))
        if any(cap not in CAPABILITIES for cap in caps):
            raise ObservationError(f"unknown capability in provides: {caps!r}")
        object.__setattr__(self, "provides", caps)
        detections = tuple(_normalise_detection(item) for item in self.detections)
        object.__setattr__(self, "detections", detections)
        object.__setattr__(self, "classifications", tuple(self.classifications))
        object.__setattr__(self, "masks", tuple(self.masks))
        object.__setattr__(self, "scalars", tuple(self.scalars))
        if self.frame_width is not None and (not isinstance(self.frame_width, int) or self.frame_width <= 0):
            raise ObservationError("frameWidth must be a positive integer")
        if self.frame_height is not None and (not isinstance(self.frame_height, int) or self.frame_height <= 0):
            raise ObservationError("frameHeight must be a positive integer")
        if len(set(self.lost_track_ids)) != len(self.lost_track_ids):
            raise ObservationError("lostTrackIds must be unique")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ObservationEnvelope":
        if not isinstance(value, Mapping):
            raise ObservationError("observation must be an object")
        allowed = {"sourceId", "frameSeq", "capturedAtUs", "frameWidth", "frameHeight", "model", "provides", "detections", "classifications", "masks", "scalars", "lostTrackIds"}
        unknown = set(value) - allowed
        if unknown:
            raise ObservationError(f"unknown observation fields: {sorted(unknown)!r}")
        return cls(
            str(value.get("sourceId", "")), value.get("frameSeq", -1), value.get("capturedAtUs", -1),
            tuple(value.get("provides", ())), tuple(value.get("detections", ())),
            tuple(Classification.from_mapping(v) for v in value.get("classifications", ())),
            tuple(Mask.from_mapping(v) for v in value.get("masks", ())),
            tuple(Scalar.from_mapping(v) for v in value.get("scalars", ())),
            value.get("frameWidth"), value.get("frameHeight"), value.get("model"),
            tuple(value.get("lostTrackIds", ())),
        )

    @property
    def actual_capabilities(self) -> frozenset[str]:
        caps: set[str] = set()
        if any("box" in d for d in self.detections): caps.add("BOX")
        if any(d.get("trackId", d.get("track_id")) is not None for d in self.detections): caps.add("TRACK")
        if self.masks: caps.add("MASK")
        if self.scalars: caps.add("SCALAR")
        return frozenset(caps)

    @property
    def capability_mismatches(self) -> tuple[str, ...]:
        actual = self.actual_capabilities
        declared = set(self.provides)
        return tuple(sorted((declared - actual) | (actual - declared)))

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"sourceId": self.source_id, "frameSeq": self.frame_seq, "capturedAtUs": self.captured_at_us, "provides": list(self.provides), "detections": list(self.detections), "classifications": [v.to_mapping() for v in self.classifications], "masks": [v.to_mapping() for v in self.masks], "scalars": [v.to_mapping() for v in self.scalars]}
        if self.frame_width is not None: payload["frameWidth"] = self.frame_width
        if self.frame_height is not None: payload["frameHeight"] = self.frame_height
        if self.model is not None: payload["model"] = dict(self.model)
        if self.lost_track_ids: payload["lostTrackIds"] = list(self.lost_track_ids)
        return payload


@dataclass(frozen=True, slots=True)
class Rejection:
    code: str
    message: str
    rule_id: str | None = None
    source_id: str | None = None
    missing: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        out: dict[str, Any] = {"accepted": False, "code": self.code, "message": self.message}
        if self.rule_id is not None: out["ruleId"] = self.rule_id
        if self.source_id is not None: out["sourceId"] = self.source_id
        if self.missing: out["missing"] = list(self.missing)
        return out


_OPERATOR_REQUIREMENTS = {
    "IN_REGION": ("BOX",), "LINE_CROSS": ("BOX", "TRACK"), "DWELL": ("BOX", "TRACK"),
    "AREA_RATIO": ("BOX",), "COUNT": ("BOX",),
}


def validate_operator_compatibility(observation: ObservationEnvelope | Mapping[str, Any], operator: str, *, subject_kind: str = "track", rule_id: str | None = None) -> Rejection | None:
    """Return a structured rejection, or ``None`` when the source can support it."""
    envelope = observation if isinstance(observation, ObservationEnvelope) else ObservationEnvelope.from_mapping(observation)
    op = str(operator).upper()
    if subject_kind == "frame" and op in {"DWELL", "LINE_CROSS", "ABSENCE"}:
        return Rejection("SUBJECT_KIND_UNSUPPORTED", f"{op} cannot bind to frame: subject", rule_id, envelope.source_id)
    required = set(_OPERATOR_REQUIREMENTS.get(op, ()))
    missing = tuple(sorted(required - set(envelope.actual_capabilities)))
    if missing:
        return Rejection("CAPABILITY_UNSATISFIED", f"{op} requires {', '.join(missing)} capability", rule_id, envelope.source_id, missing)
    return None


@dataclass
class ObservationIngestor:
    """Per-source monotonic gate. Frame sequence may jump (latest-only drops)."""
    _last_captured_at_us: dict[str, int] = field(default_factory=dict)
    capability_mismatch_count: int = 0

    def ingest(self, observation: ObservationEnvelope | Mapping[str, Any]) -> ObservationEnvelope:
        envelope = observation if isinstance(observation, ObservationEnvelope) else ObservationEnvelope.from_mapping(observation)
        previous = self._last_captured_at_us.get(envelope.source_id)
        if previous is not None and envelope.captured_at_us < previous:
            raise NonMonotonicTimestampError(envelope.source_id, previous, envelope.captured_at_us)
        self._last_captured_at_us[envelope.source_id] = envelope.captured_at_us
        self.capability_mismatch_count += len(envelope.capability_mismatches)
        return envelope

    accept = ingest

    def last_timestamp(self, source_id: str) -> int | None:
        return self._last_captured_at_us.get(source_id)


def ingest_observation(observation: ObservationEnvelope | Mapping[str, Any], state: ObservationIngestor | None = None) -> ObservationEnvelope:
    """Convenience entry point used by adapters and tests."""
    return (state or ObservationIngestor()).ingest(observation)


def _label(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ObservationError(f"{field_name} must be a non-empty string")


def _confidence(value: float, field_name: str) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ObservationError(f"{field_name} must be within [0, 1]")


def _validate_detection(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise ObservationError("detection must be an object")
    _label(value.get("label", value.get("class_name", "")), "detection.label")
    _confidence(float(value.get("confidence", -1)), "detection.confidence")
    box = value.get("box")
    if box is not None:
        if not isinstance(box, Mapping):
            raise ObservationError("detection.box must be an object")
        try:
            x, y, w, h = (float(box[key]) for key in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservationError("detection.box requires x, y, w and h") from exc
        if not all(math.isfinite(v) for v in (x, y, w, h)) or not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1 and y + h <= 1):
            raise ObservationError("detection.box must be normalized and inside the frame")
    track_id = value.get("trackId", value.get("track_id"))
    if track_id is not None and (not isinstance(track_id, str) or not SOURCE_ID_PATTERN.match(track_id)):
        raise ObservationError("detection.trackId has invalid format")


def _normalise_detection(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ObservationError("detection must be an object")
    _validate_detection(value)
    out: dict[str, Any] = {
        "label": value.get("label", value.get("class_name")),
        "confidence": round(float(value["confidence"]), 6),
    }
    if value.get("box") is not None:
        box = value["box"]
        out["box"] = {key: round(float(box[key]), 6) for key in ("x", "y", "w", "h")}
    track_id = value.get("trackId", value.get("track_id"))
    if track_id is not None:
        out["trackId"] = track_id
    return out


# Friendly aliases used by adapters and older prototypes.
Observation = ObservationEnvelope
ObservationState = ObservationIngestor
check_operator_compatibility = validate_operator_compatibility
