"""Alert disposition and false-positive feedback store (M11-T09).

The evaluator/lifecycle modules deliberately do not perform I/O.  This small
in-memory store is the service boundary for human disposition: it keeps an
append-only action history and creates safe, portable training entries for
false positives. PostgreSQL is used when DATABASE_URL is configured; the
in-memory implementation remains available for isolated tests.
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

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from ..database import (
    AlertDispositionActionRecord,
    AlertEventRecord,
    DatabaseManager,
    FalsePositiveFeedbackRecord,
    database,
)


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
    """Stable alert-store API backed by PostgreSQL or explicit process memory."""

    def __init__(self, database_manager: DatabaseManager | None = None) -> None:
        self._events: dict[str, dict[str, Any]] = {}
        self._feedback: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._database = database_manager

    @property
    def database_manager(self) -> DatabaseManager | None:
        return self._database

    def configure_database(self, database_manager: DatabaseManager | None) -> None:
        """Switch the backing store before use; tests use this to isolate global state."""
        with self._lock:
            self._database = database_manager

    @staticmethod
    def _event_item(event: Mapping[str, Any] | Any, evidence: Mapping[str, Any] | None, detections: Any) -> dict[str, Any]:
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
        return item

    @staticmethod
    def _row_mapping(session, row: AlertEventRecord) -> dict[str, Any]:
        item = deepcopy(dict(row.payload))
        actions = session.scalars(
            select(AlertDispositionActionRecord)
            .where(AlertDispositionActionRecord.event_id == row.event_id)
            .order_by(AlertDispositionActionRecord.acted_at_us, AlertDispositionActionRecord.id)
        ).all()
        history = [
            {
                "status": action.status,
                "actor": action.actor,
                "actedAtUs": action.acted_at_us,
                **({"note": action.note} if action.note else {}),
            }
            for action in actions
        ]
        if history:
            item["disposition"] = {**history[-1], "history": history}
        else:
            item.setdefault("disposition", {"status": "OPEN", "actor": None, "actedAtUs": None})
        return item

    @staticmethod
    def _apply_row(row: AlertEventRecord, item: Mapping[str, Any]) -> None:
        disposition = item.get("disposition") or {}
        row.rule_id = item.get("ruleId")
        row.source_id = item.get("sourceId")
        row.subject_key = item.get("subjectKey")
        row.state = item.get("state")
        row.severity = item.get("severity")
        row.disposition_status = str(disposition.get("status") or "OPEN")
        row.payload = deepcopy(dict(item))

    def register(self, event: Mapping[str, Any] | Any, *, evidence: Mapping[str, Any] | None = None,
                 detections: Any = None) -> dict[str, Any]:
        item = self._event_item(event, evidence, detections)
        event_id = item["eventId"]
        if self._database is not None:
            with self._database.session() as session:
                query = select(AlertEventRecord).where(AlertEventRecord.event_id == event_id)
                if self._database.backend == "postgresql":
                    query = query.with_for_update()
                row = session.scalar(query)
                if row is None:
                    if self._database.backend == "postgresql":
                        # Multiple app workers can ingest the same event at once.
                        # Let PostgreSQL arbitrate the first insert, then read the
                        # committed winner instead of surfacing a primary-key race.
                        disposition = item.get("disposition") or {}
                        session.execute(
                            postgres_insert(AlertEventRecord)
                            .values(
                                event_id=event_id,
                                rule_id=item.get("ruleId"),
                                source_id=item.get("sourceId"),
                                subject_key=item.get("subjectKey"),
                                state=item.get("state"),
                                severity=item.get("severity"),
                                disposition_status=str(disposition.get("status") or "OPEN"),
                                payload=deepcopy(item),
                            )
                            .on_conflict_do_nothing(index_elements=[AlertEventRecord.event_id])
                        )
                        row = session.scalar(query)
                    else:
                        row = AlertEventRecord(event_id=event_id, payload={})
                        session.add(row)
                if row is None:
                    raise RuntimeError("event insert did not return a row")
                # register() updates the event facts, but disposition() is the
                # only operation allowed to change an existing disposition.
                # This prevents a duplicate mobile ingest from resetting an ACK
                # or FALSE_POSITIVE action to OPEN.
                if row.disposition_status != "OPEN":
                    existing = dict(row.payload)
                    item["disposition"] = deepcopy(existing.get("disposition") or {
                        "status": row.disposition_status,
                        "actor": None,
                        "actedAtUs": None,
                    })
                    if existing.get("state") == "ENDED":
                        item["state"] = "ENDED"
                    if existing.get("falsePositiveEntryId"):
                        item["falsePositiveEntryId"] = existing["falsePositiveEntryId"]
                self._apply_row(row, item)
                session.flush()
                return self._row_mapping(session, row)
        with self._lock:
            self._events[event_id] = item
            return deepcopy(item)

    def get(self, event_id: str) -> dict[str, Any]:
        if self._database is not None:
            with self._database.session() as session:
                row = session.get(AlertEventRecord, event_id)
                if row is None:
                    raise KeyError(event_id)
                return self._row_mapping(session, row)
        with self._lock:
            if event_id not in self._events:
                raise KeyError(event_id)
            return deepcopy(self._events[event_id])

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if self._database is not None:
            with self._database.session() as session:
                query = select(AlertEventRecord)
                if status:
                    query = query.where(AlertEventRecord.disposition_status == status)
                rows = session.scalars(query.order_by(AlertEventRecord.updated_at.desc())).all()
                return [self._row_mapping(session, row) for row in rows]
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
        if self._database is not None:
            with self._database.session() as session:
                row = session.scalar(
                    select(AlertEventRecord)
                    .where(AlertEventRecord.event_id == event_id)
                    .with_for_update()
                )
                if row is None:
                    raise KeyError(event_id)
                existing = session.scalar(
                    select(AlertDispositionActionRecord).where(
                        AlertDispositionActionRecord.event_id == event_id,
                        AlertDispositionActionRecord.status == status,
                        AlertDispositionActionRecord.actor == actor,
                        AlertDispositionActionRecord.acted_at_us == action_time,
                    )
                )
                if existing is not None:
                    return self._row_mapping(session, row)
                action = AlertDispositionActionRecord(
                    event_id=event_id,
                    status=status,
                    actor=actor,
                    acted_at_us=action_time,
                    note=str(note)[:1000] if note else None,
                )
                session.add(action)
                session.flush()
                item = deepcopy(dict(row.payload))
                action_mapping = {"status": status, "actor": actor, "actedAtUs": action_time}
                if note:
                    action_mapping["note"] = str(note)[:1000]
                item["disposition"] = action_mapping
                if status == "FALSE_POSITIVE":
                    item["state"] = "ENDED"
                    entry_id = "fp-" + hashlib.sha256(f"{event_id}\0{action_time}".encode()).hexdigest()[:24]
                    raw_evidence = dict(item.get("evidence") or {})
                    if evidence:
                        raw_evidence.update(deepcopy(dict(evidence)))
                    image_ref = _safe_ref(screenshot or raw_evidence.get("snapshotUri") or raw_evidence.get("image"))
                    thresholds = effective_thresholds if effective_thresholds is not None else item.get("effectiveThresholds", {})
                    detections = detection_results if detection_results is not None else item.get("detectionResults", item.get("detections", []))
                    training = sanitise_training_entry({
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
                    })
                    if session.get(FalsePositiveFeedbackRecord, entry_id) is None:
                        session.add(FalsePositiveFeedbackRecord(
                            entry_id=entry_id,
                            event_id=event_id,
                            action_id=action.id,
                            payload=training,
                        ))
                    item["falsePositiveEntryId"] = entry_id
                self._apply_row(row, item)
                session.flush()
                return self._row_mapping(session, row)
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
                item["state"] = "ENDED"
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
        if self._database is not None:
            with self._database.session() as session:
                rows = session.scalars(
                    select(FalsePositiveFeedbackRecord).order_by(FalsePositiveFeedbackRecord.created_at)
                ).all()
                return [deepcopy(dict(row.payload)) for row in rows]
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
        if self._database is not None:
            raise RuntimeError("reset is disabled for the persistent alert store")
        with self._lock:
            self._events.clear()
            self._feedback.clear()


alert_disposition_store = AlertDispositionStore(database if database.enabled else None)
DispositionStore = AlertDispositionStore

__all__ = ["AlertDispositionStore", "DispositionStore", "DispositionAction", "alert_disposition_store",
           "sanitise_training_entry", "sanitize_training_entry"]
