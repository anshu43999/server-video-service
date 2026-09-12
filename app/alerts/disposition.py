"""Alert disposition and false-positive feedback store (M11-T09).

The evaluator/lifecycle modules deliberately do not perform I/O.  This small
in-memory store is the service boundary for human disposition: it keeps an
append-only action history and creates safe, portable training entries for
false positives.  A database adapter can replace this class without changing
the HTTP contract.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePath
import re
import threading
import time
from typing import Any, Mapping


STATUSES = {"ACKNOWLEDGED", "FALSE_POSITIVE", "CLOSED"}
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}|/)")
_SECRET_KEY = re.compile(r"(?:token|secret|password|authorization|credential|api[-_]?key|cookie)", re.I)


def _safe_ref(value: Any) -> str | None:
    """Return a portable evidence reference, never a local absolute path."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # URLs are useful to clients, but query strings commonly contain tokens.
    if raw.startswith(("http://", "https://")):
        return raw.split("?", 1)[0].split("#", 1)[0]
    if _ABSOLUTE_PATH.match(raw) or raw.lower().startswith("file:"):
        name = PurePath(raw.replace("\\", "/")).name
        return f"evidence/{name}" if name else None
    return raw.lstrip("./")


def _safe_value(value: Any, *, key: str = "") -> Any:
    """Recursively redact credentials and make paths portable for export."""
    if _SECRET_KEY.search(key):
        return None
    if isinstance(value, Mapping):
        return {str(k): _safe_value(v, key=str(k)) for k, v in value.items()
                if not _SECRET_KEY.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [_safe_value(v, key=key) for v in value]
    if isinstance(value, str) and (_ABSOLUTE_PATH.match(value) or value.lower().startswith("file:")):
        return _safe_ref(value)
    return value


def sanitise_training_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Public sanitizer used by tests and export adapters."""
    return _safe_value(deepcopy(dict(entry)))


# American spelling kept as a compatibility alias for API/integration code.
sanitize_training_entry = sanitise_training_entry


@dataclass(frozen=True)
class DispositionAction:
    status: str
    actor: str
    acted_at_us: int


class AlertDispositionStore:
    """Thread-safe event snapshot and false-positive feedback store."""

    def __init__(self) -> None:
        self._events: dict[str, dict[str, Any]] = {}
        self._feedback: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def register(self, event: Mapping[str, Any] | Any, *, evidence: Mapping[str, Any] | None = None,
                 detections: Any = None) -> dict[str, Any]:
        if hasattr(event, "to_mapping"):
            event = event.to_mapping()
        item = deepcopy(dict(event))
        event_id = str(item.get("eventId") or item.get("event_id") or "")
        if not event_id:
            raise ValueError("eventId is required")
        item["eventId"] = event_id
        item.setdefault("disposition", {"status": "OPEN", "actor": None, "actedAtUs": None})
        item.setdefault("evidence", deepcopy(evidence or {}))
        if detections is not None:
            item.setdefault("detectionResults", deepcopy(detections))
        with self._lock:
            self._events[event_id] = item
            return deepcopy(item)

    def get(self, event_id: str) -> dict[str, Any]:
        with self._lock:
            if event_id not in self._events:
                raise KeyError(event_id)
            return deepcopy(self._events[event_id])

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            values = self._events.values()
            if status:
                values = (e for e in values if (e.get("disposition") or {}).get("status") == status)
            return [deepcopy(e) for e in values]

    @staticmethod
    def _timestamp(value: Any) -> int:
        if value is None:
            return time.time_ns() // 1000
        result = int(value)
        if result < 0:
            raise ValueError("actedAtUs must be non-negative")
        return result

    def dispose(self, event_id: str, status: str, actor: str, *, acted_at_us: Any = None,
                screenshot: str | None = None, evidence: Mapping[str, Any] | None = None,
                effective_thresholds: Mapping[str, Any] | None = None,
                detection_results: Any = None, note: str | None = None) -> dict[str, Any]:
        status = str(status).upper()
        if status not in STATUSES:
            raise ValueError(f"unsupported disposition status: {status}")
        actor = str(actor or "").strip()
        if not actor or len(actor) > 128:
            raise ValueError("actor is required")
        action_time = self._timestamp(acted_at_us)
        with self._lock:
            if event_id not in self._events:
                raise KeyError(event_id)
            item = self._events[event_id]
            disposition = dict(item.get("disposition") or {})
            history = list(disposition.get("history") or [])
            action = {"status": status, "actor": actor, "actedAtUs": action_time}
            if note:
                action["note"] = str(note)[:1000]
            history.append(action)
            disposition.update({"status": status, "actor": actor, "actedAtUs": action_time, "history": history})
            item["disposition"] = disposition
            # False positives are terminal for the current event and produce
            # one deterministic feedback entry per action.
            if status == "FALSE_POSITIVE":
                item.setdefault("state", "ENDED")
                entry_id = "fp-" + hashlib.sha256(f"{event_id}\0{action_time}".encode()).hexdigest()[:24]
                raw_evidence = dict(item.get("evidence") or {})
                if evidence:
                    raw_evidence.update(deepcopy(dict(evidence)))
                image_ref = _safe_ref(screenshot or raw_evidence.get("snapshotUri") or raw_evidence.get("image"))
                thresholds = effective_thresholds if effective_thresholds is not None else item.get("effectiveThresholds", {})
                detections = detection_results if detection_results is not None else item.get("detectionResults", item.get("detections", []))
                training = {
                    "entryId": entry_id,
                    "eventId": event_id,
                    "label": "false_positive",
                    "image": image_ref,
                    "screenshot": image_ref,
                    "annotations": [],
                    "detectionResults": deepcopy(detections),
                    "effectiveThresholds": deepcopy(dict(thresholds or {})),
                    "thresholds": deepcopy(dict(thresholds or {})),
                    "sourceId": item.get("sourceId"),
                    "subjectKey": item.get("subjectKey"),
                    "capturedAtUs": item.get("confirmedAtUs", item.get("startedAtUs")),
                    "ruleId": item.get("ruleId"),
                    "ruleVersion": item.get("ruleVersion"),
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
                self._feedback[entry_id] = sanitise_training_entry(training)
                item["falsePositiveEntryId"] = entry_id
            self._events[event_id] = item
            return deepcopy(item)

    def feedback(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(v) for v in self._feedback.values()]

    def acknowledge(self, event_id: str, actor: str, *, acted_at_us: Any = None, note: str | None = None) -> dict[str, Any]:
        return self.dispose(event_id, "ACKNOWLEDGED", actor, acted_at_us=acted_at_us, note=note)

    def mark_false_positive(self, event_id: str, actor: str, **kwargs: Any) -> dict[str, Any]:
        return self.dispose(event_id, "FALSE_POSITIVE", actor, **kwargs)

    def export_json(self) -> bytes:
        with self._lock:
            entries = self.feedback()
            payload = {"format": "aiyolo-false-positive-v1", "entries": entries, "trainingEntries": entries}
        return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")

    def export_false_positives(self) -> list[dict[str, Any]]:
        """Return sanitized entries for callers that do not need a byte stream."""
        return self.feedback()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._feedback.clear()


alert_disposition_store = AlertDispositionStore()
DispositionStore = AlertDispositionStore

__all__ = ["AlertDispositionStore", "DispositionStore", "DispositionAction", "alert_disposition_store",
           "sanitise_training_entry", "sanitize_training_entry"]
