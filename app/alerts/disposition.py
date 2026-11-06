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
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy import select
from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from ..database import (
    AlertDispositionActionRecord,
    AlertEventRecord,
    DEFAULT_PROJECT_ID,
    DatabaseManager,
    FalsePositiveFeedbackRecord,
    PlatformAuditEventRecord,
    ProjectRecord,
    ServicePrincipalRecord,
    database,
)


STATUSES = {"ACKNOWLEDGED", "FALSE_POSITIVE", "CLOSED"}
from .mobile_control import (MobileAlertControlStore, check_disposition_revision,
                             disposition_committed, disposition_revision, latest_original_requests)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}|/)")
_SECRET_KEY = re.compile(r"(?:token|secret|password|authorization|credential|api[-_]?key|cookie)", re.I)


def _safe_ref(value: Any) -> str | None:
    """Return a portable evidence reference, never a local absolute path."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Inline image payloads are never training references. Callers that know
    # the event identity should replace these with its authenticated API URI.
    if raw.lower().startswith("data:image/"):
        return None
    # Keep the authenticated application evidence route portable; unlike a
    # filesystem path it is a safe, project-scoped identifier without a token.
    if raw.startswith(("/aiyoloapi/projects/", "/aiyoloapi/alerts/")) and ".." not in raw.split("/"):
        return raw.split("?", 1)[0].split("#", 1)[0]
    # URLs are useful to clients, but query strings commonly contain tokens.
    if raw.lower().startswith(("http://", "https://")):
        parsed = urlsplit(raw)
        return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
    if _ABSOLUTE_PATH.match(raw) or raw.lower().startswith("file:"):
        name = PurePath(raw.replace("\\", "/")).name
        return f"evidence/{name}" if name and name != "evidence" else None
    portable = raw.lstrip("./")
    while portable.startswith("evidence/evidence/"):
        portable = portable[len("evidence/"):]
    return portable


def _training_evidence_ref(value: Any, project_id: str, event_id: str) -> str | None:
    """Normalize a supplied reference and never persist a caller's data URL."""
    safe = _safe_ref(value)
    path = urlsplit(safe).path if safe else ""
    if safe is not None and not path.startswith(("/aiyoloapi/projects/", "/aiyoloapi/alerts/")):
        return safe
    if safe is None and not (isinstance(value, str) and value.lower().startswith("data:image/")):
        return None
    versioned = re.search(r"/evidence/(thumbnail|original)/([1-9][0-9]*)$", path)
    suffix = f"/{versioned[1]}/{versioned[2]}" if versioned else ""
    return (f"/aiyoloapi/projects/{quote(project_id, safe='')}/alerts/"
            f"{quote(event_id, safe='')}/evidence{suffix}")


def _feedback_evidence(evidence: Mapping[str, Any], screenshot: Any,
                       project_id: str, event_id: str) -> dict[str, Any]:
    value = screenshot or evidence.get("snapshotUri") or evidence.get("image") or evidence.get("snapshotDataUrl")
    # New uploads have independent versions, without a legacy snapshotUri.
    if not value:
        for kind in ("original", "thumbnail"):
            versions = evidence.get(kind)
            live = [str(version) for version, ref in versions.items()
                    if str(version).isdigit() and int(version) > 0 and isinstance(ref, Mapping)
                    and ref.get("objectStorage") and ref.get("retentionState") != "DELETED"] if isinstance(versions, Mapping) else []
            if live:
                value = (f"/aiyoloapi/projects/{quote(project_id, safe='')}/alerts/"
                         f"{quote(event_id, safe='')}/evidence/{kind}/{max(live, key=int)}")
                break
    ref = _training_evidence_ref(value, project_id, event_id)
    return {"image": ref, "screenshot": ref,
            "evidenceUnavailableReason": None if ref else "evidence_not_uploaded"}


def public_training_entry(entry: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    """Sanitize historical feedback at read/export boundaries without overwriting it."""
    event_id = str(entry.get("eventId") or "")
    result = sanitise_training_entry(entry)
    result.update(_feedback_evidence(entry, None, project_id, event_id))
    if not result.get("image") and entry.get("evidenceUnavailableReason") in {
        "evidence_not_uploaded", "reference_not_exportable", "evidence_expired",
        "evidence_deleted", "object_missing",
    }:
        result["evidenceUnavailableReason"] = entry["evidenceUnavailableReason"]
    result["projectId"] = project_id
    return result


def public_alert_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return image-free metadata without deleting the legacy backing image."""
    item = deepcopy(dict(event))
    item["dispositionRevision"] = disposition_revision(item)
    requests = item.pop("_originalRequests", {})
    if requests:
        latest = latest_original_requests({"_originalRequests": requests})[0]
        item["originalRequest"] = {k: v for k, v in latest.items() if k != "receipt"}
    item.pop("_originalOperations", None)
    item.pop("mobileProducer", None)
    project_id, event_id = str(item.get("projectId") or DEFAULT_PROJECT_ID), str(item.get("eventId") or "")
    evidence = item.get("evidence")
    if not isinstance(evidence, dict):
        return _image_free_value(item)
    inline = any(
        isinstance(evidence.get(key), str) and evidence[key].lower().startswith("data:image/")
        for key in ("snapshotUri", "image", "snapshotDataUrl")
    )
    evidence.pop("snapshotDataUrl", None)
    evidence.pop("localPath", None)
    if inline:
        evidence.pop("image", None)
        evidence["snapshotUri"] = (
            f"/aiyoloapi/projects/{quote(project_id, safe='')}/alerts/"
            f"{quote(event_id, safe='')}/evidence"
        )
    else:
        for key in ("snapshotUri", "image"):
            if key in evidence:
                evidence[key] = _training_evidence_ref(evidence[key], project_id, event_id)
    return _image_free_value(item)


def _image_free_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _image_free_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_image_free_value(child) for child in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if isinstance(value, str) and value.strip().lower().startswith("data:image/"):
        return None
    return value


def _safe_value(value: Any, *, key: str = "") -> Any:
    """Recursively redact credentials and make paths portable for export."""
    if _SECRET_KEY.search(key):
        return None
    if isinstance(value, Mapping):
        return {str(k): _safe_value(v, key=str(k)) for k, v in value.items()
                if not _SECRET_KEY.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [_safe_value(v, key=key) for v in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if isinstance(value, str) and value.strip().lower().startswith("data:image/"):
        return None
    if isinstance(value, str) and (_ABSOLUTE_PATH.match(value) or value.lower().startswith(("file:", "http://", "https://"))):
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


class AlertDispositionStore(MobileAlertControlStore):
    """Stable alert-store API backed by PostgreSQL or explicit process memory."""

    def __init__(self, database_manager: DatabaseManager | None = None) -> None:
        self._events: dict[tuple[str, str], dict[str, Any]] = {}
        self._feedback: dict[tuple[str, str], dict[str, Any]] = {}
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
    def _event_item(event: Mapping[str, Any] | Any, evidence: Mapping[str, Any] | None,
                    detections: Any, project_id: str) -> dict[str, Any]:
        if hasattr(event, "to_mapping"):
            event = event.to_mapping()
        item = deepcopy(dict(event))
        event_id = str(item.get("eventId") or item.get("event_id") or "")
        if not event_id:
            raise ValueError("eventId is required")
        supplied_project = item.get("projectId") or item.get("project_id")
        if supplied_project is not None and str(supplied_project) != project_id:
            raise ValueError("event projectId does not match the authenticated project")
        item["eventId"] = event_id
        item["projectId"] = project_id
        item.pop("project_id", None)
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
            .where(
                AlertDispositionActionRecord.project_id == row.project_id,
                AlertDispositionActionRecord.event_id == row.event_id,
            )
            .order_by(AlertDispositionActionRecord.id)
        ).all()
        history = [
            {
                "status": action.status,
                "actor": action.actor,
                "actedAtUs": action.acted_at_us,
                **({"operationId": action.operation_id} if action.operation_id else {}),
                **({"note": action.note} if action.note else {}),
            }
            for action in actions
        ]
        if history:
            item["disposition"] = {**history[-1], "history": history}
        else:
            disposition = dict(item.get("disposition") or {})
            disposition["status"] = row.disposition_status or disposition.get("status") or "OPEN"
            disposition.setdefault("actor", None)
            disposition.setdefault("actedAtUs", None)
            item["disposition"] = disposition
        item["dispositionRevision"] = disposition_revision(item)
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
                 detections: Any = None, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        item = self._event_item(event, evidence, detections, project_id)
        event_id = item["eventId"]
        if self._database is not None:
            with self._database.session() as session:
                query = select(AlertEventRecord).where(
                    AlertEventRecord.project_id == project_id,
                    AlertEventRecord.event_id == event_id,
                )
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
                                project_id=project_id,
                                event_id=event_id,
                                rule_id=item.get("ruleId"),
                                source_id=item.get("sourceId"),
                                subject_key=item.get("subjectKey"),
                                state=item.get("state"),
                                severity=item.get("severity"),
                                disposition_status=str(disposition.get("status") or "OPEN"),
                                payload=deepcopy(item),
                            )
                            .on_conflict_do_nothing(
                                index_elements=[AlertEventRecord.project_id, AlertEventRecord.event_id]
                            )
                        )
                        row = session.scalar(query)
                    else:
                        row = AlertEventRecord(project_id=project_id, event_id=event_id, payload={})
                        session.add(row)
                if row is None:
                    raise RuntimeError("event insert did not return a row")
                if row.payload.get("provenance") is not None:
                    if item.get("provenance") not in (None, row.payload["provenance"]):
                        raise ValueError("event_identity_conflict")
                    item["provenance"] = deepcopy(row.payload["provenance"])
                    item["model"] = deepcopy(row.payload.get("model"))
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
            existing = self._events.get((project_id, event_id), {})
            if existing.get("provenance") is not None:
                if item.get("provenance") not in (None, existing["provenance"]):
                    raise ValueError("event_identity_conflict")
                item["provenance"] = deepcopy(existing["provenance"])
                item["model"] = deepcopy(existing.get("model"))
            self._events[(project_id, event_id)] = item
            return deepcopy(item)

    def register_mobile_fact(self, event: Mapping[str, Any], project_id: str) -> tuple[dict, bool]:
        """Serialize v1 fact replays with evidence/disposition writers across workers."""
        incoming = self._event_item(event, None, None, project_id)

        def merge(current):
            if current.get("mobileProducer") != incoming.get("mobileProducer"):
                raise ValueError("producer_identity_conflict")
            if any(current.get(key) != incoming.get(key)
                   for key in ("sourceId", "ruleId", "subjectKey", "startedAtUs", "origin", "provenance")):
                raise ValueError("event_identity_conflict")
            item = deepcopy(current)
            item.update({key: value for key, value in incoming.items()
                         if value is not None and key not in {"disposition", "evidence"}})
            # L1 is never authority for the durable evidence references or actions.
            if current.get("state") == "ENDED":
                item["state"] = "ENDED"
            return item

        with self._lock:
            if self._database is not None:
                with self._database.session() as session:
                    # A project lock also serializes first inserts (no event row yet).
                    project = session.scalar(select(ProjectRecord).where(
                        ProjectRecord.project_id == project_id).with_for_update())
                    if project is None or project.lifecycle_state != "ACTIVE":
                        raise HTTPException(404, detail={"code": "project_not_found"})
                    row = session.scalar(select(AlertEventRecord).where(
                        AlertEventRecord.project_id == project_id,
                        AlertEventRecord.event_id == incoming["eventId"]).with_for_update())
                    created = row is None
                    if created:
                        row = AlertEventRecord(project_id=project_id, event_id=incoming["eventId"], payload={})
                        session.add(row)
                    item = incoming if created else merge(self._row_mapping(session, row))
                    self._apply_row(row, item)
                    session.flush()
                    return self._row_mapping(session, row), created
            key = (project_id, incoming["eventId"])
            created = key not in self._events
            item = incoming if created else merge(self._events[key])
            self._events[key] = deepcopy(item)
            return deepcopy(item), created

    def register_service_once(self, event: Mapping[str, Any], project_id: str, *, service_revision: int) -> tuple[dict, bool]:
        """Immutable machine event: retries cannot overwrite facts or human actions.

        The project row serializes first inserts across PostgreSQL workers.
        Memory/SQLite also use the store lock. Evidence uses a content-qualified
        key so a losing request cannot overwrite the winner's object.
        """
        item = self._event_item(event, None, None, project_id)
        def existing_result(current):
            if (current.get("servicePrincipalId") != item.get("servicePrincipalId")
                    or current.get("serviceIngestDigest") != item.get("serviceIngestDigest")):
                raise ValueError("service_event_conflict")
            return deepcopy(current), False
        with self._lock:
            if self._database is not None:
                with self._database.session() as session:
                    principal = session.scalar(select(ServicePrincipalRecord).where(
                        ServicePrincipalRecord.principal_id == item.get("servicePrincipalId"),
                        ServicePrincipalRecord.project_id == project_id,
                    ).with_for_update())
                    expires = principal.expires_at if principal is not None else None
                    if expires is not None and expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if (principal is None or principal.revoked_at is not None
                            or principal.revision != service_revision
                            or expires <= datetime.now(timezone.utc)):
                        raise HTTPException(401, detail={"code": "service_credential_changed"})
                    project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id).with_for_update())
                    if project is None or project.lifecycle_state != "ACTIVE" or "project.alerts.ingest" not in principal.capabilities:
                        raise HTTPException(403, detail={"code": "service_ingest_not_allowed"})
                    row = session.get(AlertEventRecord, (project_id, item["eventId"]))
                    if row is not None:
                        return existing_result(row.payload)
                    row = AlertEventRecord(project_id=project_id, event_id=item["eventId"], payload={})
                    self._apply_row(row, item)
                    session.add(row)
                    session.flush()
                    return deepcopy(item), True
            key = (project_id, item["eventId"])
            if key in self._events:
                return existing_result(self._events[key])
            self._events[key] = deepcopy(item)
            return deepcopy(item), True

    def get(self, event_id: str, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        if self._database is not None:
            with self._database.session() as session:
                row = session.get(AlertEventRecord, (project_id, event_id))
                if row is None:
                    raise KeyError(event_id)
                return self._row_mapping(session, row)
        with self._lock:
            key = (project_id, event_id)
            if key not in self._events:
                raise KeyError(event_id)
            return deepcopy(self._events[key])

    def attach_verification(self, event_id: str, result: Mapping[str, Any], project_id: str) -> None:
        """Merge only the annotation; concurrent upload/disposition facts are preserved."""
        with self._lock:
            if self._database is not None:
                with self._database.session() as session:
                    row = session.scalar(select(AlertEventRecord).where(
                        AlertEventRecord.project_id == project_id,
                        AlertEventRecord.event_id == event_id,
                    ).with_for_update())
                    if row is None:
                        raise KeyError(event_id)
                    item = deepcopy(dict(row.payload))
                    current = item.get("verification") or {}
                    if (int(current.get("requestedAtUs") or 0), bool(current.get("completedAtUs"))) <= (
                            int(result.get("requestedAtUs") or 0), bool(result.get("completedAtUs"))):
                        item["verification"] = deepcopy(dict(result))
                        row.payload = item
                return
            item = self._events[(project_id, event_id)]
            current = item.get("verification") or {}
            if (int(current.get("requestedAtUs") or 0), bool(current.get("completedAtUs"))) <= (
                    int(result.get("requestedAtUs") or 0), bool(result.get("completedAtUs"))):
                item["verification"] = deepcopy(dict(result))

    def register_evidence(self, event_id: str, project_id: str, evidence_type: str,
                          content_version: int, reference: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        """Atomically attach one immutable tiered-evidence identity to an existing fact."""
        with self._lock:
            if self._database is not None:
                with self._database.session() as session:
                    query = select(AlertEventRecord).where(
                        AlertEventRecord.project_id == project_id,
                        AlertEventRecord.event_id == event_id,
                    )
                    if self._database.backend == "postgresql":
                        query = query.with_for_update()
                    row = session.scalar(query)
                    if row is None:
                        raise KeyError(event_id)
                    item = deepcopy(dict(row.payload))
                    evidence = item.setdefault("evidence", {})
                    group = evidence.setdefault(evidence_type, {})
                    key = str(content_version)
                    current = group.get(key)
                    if current is not None:
                        if current.get("sha256") != reference.get("sha256"):
                            raise ValueError("evidence_version_conflict")
                        return self._row_mapping(session, row), False
                    stored_reference = deepcopy(dict(reference))
                    # Retention is measured from the successful upload, not the
                    # alert's creation time. Keep the timestamp beside the
                    # immutable object reference so retries preserve it.
                    stored_reference.setdefault(
                        "uploadedAt", datetime.now(timezone.utc).isoformat()
                    )
                    stored_reference.setdefault("retentionState", "ACTIVE")
                    group[key] = stored_reference
                    row.payload = item
                    feedback_rows = session.scalars(select(FalsePositiveFeedbackRecord).where(
                        FalsePositiveFeedbackRecord.project_id == project_id,
                        FalsePositiveFeedbackRecord.event_id == event_id,
                    )).all()
                    for feedback in feedback_rows:
                        updated = sanitise_training_entry(feedback.payload)
                        updated.update(_feedback_evidence(evidence, None, project_id, event_id))
                        feedback.payload = updated
                    session.flush()
                    return self._row_mapping(session, row), True
            key = (project_id, event_id)
            item = self._events.get(key)
            if item is None:
                raise KeyError(event_id)
            item = deepcopy(item)
            evidence = item.setdefault("evidence", {})
            group = evidence.setdefault(evidence_type, {})
            version_key = str(content_version)
            current = group.get(version_key)
            if current is not None:
                if current.get("sha256") != reference.get("sha256"):
                    raise ValueError("evidence_version_conflict")
                return deepcopy(item), False
            stored_reference = deepcopy(dict(reference))
            stored_reference.setdefault(
                "uploadedAt", datetime.now(timezone.utc).isoformat()
            )
            stored_reference.setdefault("retentionState", "ACTIVE")
            group[version_key] = stored_reference
            for (feedback_project, _), feedback in self._feedback.items():
                if feedback_project == project_id and feedback.get("eventId") == event_id:
                    feedback.update(_feedback_evidence(evidence, None, project_id, event_id))
            self._events[key] = item
            return deepcopy(item), True

    def read_evidence(self, event_id: str, project_id: str, evidence_type: str,
                      content_version: int, reader):
        """Hold the owning event row lock for the complete object read operation."""
        version = str(content_version)
        with self._lock:
            if self._database is not None:
                with self._database.session() as session:
                    query = select(AlertEventRecord).where(
                        AlertEventRecord.project_id == project_id,
                        AlertEventRecord.event_id == event_id,
                    )
                    if self._database.backend == "postgresql":
                        query = query.with_for_update()
                    row = session.scalar(query)
                    if row is None:
                        raise KeyError(event_id)
                    reference = (((row.payload or {}).get("evidence") or {})
                                 .get(evidence_type, {}).get(version))
                    if not isinstance(reference, dict) or reference.get("retentionState") == "DELETED":
                        raise KeyError(version)
                    return reader(deepcopy(reference))
            event = self._events.get((project_id, event_id))
            if event is None:
                raise KeyError(event_id)
            reference = (((event.get("evidence") or {}).get(evidence_type) or {}).get(version))
            if not isinstance(reference, dict) or reference.get("retentionState") == "DELETED":
                raise KeyError(version)
            return reader(deepcopy(reference))

    def list(self, *, status: str | None = None,
             project_id: str = DEFAULT_PROJECT_ID, limit: int | None = None) -> list[dict[str, Any]]:
        if self._database is not None:
            with self._database.session() as session:
                query = select(AlertEventRecord).where(AlertEventRecord.project_id == project_id)
                if status:
                    query = query.where(AlertEventRecord.disposition_status == status)
                query = query.order_by(AlertEventRecord.updated_at.desc(), AlertEventRecord.event_id.desc())
                if limit is not None:
                    query = query.limit(limit)
                rows = session.scalars(query).all()
                return [self._row_mapping(session, row) for row in rows]
        with self._lock:
            values = (event for (pid, _), event in self._events.items() if pid == project_id)
            if status:
                values = (e for e in values if (e.get("disposition") or {}).get("status") == status)
            if limit is not None:
                import heapq
                values = heapq.nlargest(limit, values, key=lambda e: (e.get('lastSeenAtUs') or e.get('confirmedAtUs') or e.get('startedAtUs') or 0, e.get('eventId', '')))
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
                detection_results: Any = None, note: str | None = None,
                project_id: str = DEFAULT_PROJECT_ID, operation_id: str | None = None,
                request_digest: str | None = None, expected_revision: int | None = None) -> dict[str, Any]:
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
                    .where(
                        AlertEventRecord.project_id == project_id,
                        AlertEventRecord.event_id == event_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise KeyError(event_id)
                if operation_id is not None:
                    by_operation = session.scalar(
                        select(AlertDispositionActionRecord).where(
                            AlertDispositionActionRecord.project_id == project_id,
                            AlertDispositionActionRecord.event_id == event_id,
                            AlertDispositionActionRecord.operation_id == operation_id,
                        )
                    )
                    if by_operation is not None:
                        if by_operation.request_digest != request_digest:
                            raise ValueError("idempotency_conflict")
                        return self._row_mapping(session, row)
                existing = session.scalar(
                    select(AlertDispositionActionRecord).where(
                        AlertDispositionActionRecord.project_id == project_id,
                        AlertDispositionActionRecord.event_id == event_id,
                        AlertDispositionActionRecord.status == status,
                        AlertDispositionActionRecord.actor == actor,
                        AlertDispositionActionRecord.acted_at_us == action_time,
                    )
                )
                if existing is not None:
                    check_disposition_revision(self._row_mapping(session, row), expected_revision)
                    return self._row_mapping(session, row)
                revision = check_disposition_revision(self._row_mapping(session, row), expected_revision)
                if row.disposition_status == "FALSE_POSITIVE" and status != "FALSE_POSITIVE" and row.payload.get("mobileProducer"):
                    raise ValueError("disposition_terminal")
                action = AlertDispositionActionRecord(
                    project_id=project_id,
                    event_id=event_id,
                    status=status,
                    actor=actor,
                    acted_at_us=action_time,
                    operation_id=operation_id,
                    request_digest=request_digest,
                    note=str(note)[:1000] if note else None,
                )
                session.add(action)
                session.flush()
                item = deepcopy(dict(row.payload))
                action_mapping = {"status": status, "actor": actor, "actedAtUs": action_time}
                if note:
                    action_mapping["note"] = str(note)[:1000]
                item["disposition"] = action_mapping
                previous_requests = len(item.get("_originalRequests", {}))
                disposition_committed(item, revision, actor, status)
                if len(item.get("_originalRequests", {})) > previous_requests:
                    from uuid import uuid4
                    session.add(PlatformAuditEventRecord(
                        audit_id=str(uuid4()), occurred_at=datetime.now(timezone.utc),
                        action="alert.evidence.request", target_type="alert_event", target_id=event_id,
                        outcome="SUCCESS", change_summary={"projectId": project_id, "actor": actor,
                                                            "reason": "FALSE_POSITIVE"},
                        request_id=str(uuid4())))
                if status == "FALSE_POSITIVE":
                    item["state"] = "ENDED"
                    entry_id = "fp-" + hashlib.sha256(f"{event_id}\0{action_time}".encode()).hexdigest()[:24]
                    raw_evidence = dict(item.get("evidence") or {})
                    if evidence:
                        raw_evidence.update(deepcopy(dict(evidence)))
                    feedback_evidence = _feedback_evidence(raw_evidence, screenshot, project_id, event_id)
                    thresholds = effective_thresholds if effective_thresholds is not None else item.get("effectiveThresholds", {})
                    detections = detection_results if detection_results is not None else item.get("detectionResults", item.get("detections", []))
                    training = sanitise_training_entry({
                        "entryId": entry_id,
                        "projectId": project_id,
                        "eventId": event_id,
                        "label": "false_positive",
                        **feedback_evidence,
                        "annotations": [],
                        "detectionResults": deepcopy(detections),
                        "effectiveThresholds": deepcopy(dict(thresholds or {})),
                        "thresholds": deepcopy(dict(thresholds or {})),
                        "sourceId": item.get("sourceId"),
                        "provenance": deepcopy(item.get("provenance")),
                        "model": deepcopy(item.get("model")),
                        "subjectKey": item.get("subjectKey"),
                        "capturedAtUs": item.get("confirmedAtUs", item.get("startedAtUs")),
                        "ruleId": item.get("ruleId"),
                        "ruleVersion": item.get("ruleVersion"),
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                    })
                    if session.get(FalsePositiveFeedbackRecord, (project_id, entry_id)) is None:
                        session.add(FalsePositiveFeedbackRecord(
                            project_id=project_id,
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
            key = (project_id, event_id)
            if key not in self._events:
                raise KeyError(event_id)
            item = self._events[key]
            disposition = dict(item.get("disposition") or {})
            history = list(disposition.get("history") or [])
            if operation_id is not None:
                previous = next((entry for entry in history if entry.get("operationId") == operation_id), None)
                if previous is not None:
                    if previous.get("requestDigest") != request_digest:
                        raise ValueError("idempotency_conflict")
                    return deepcopy(item)
            revision = check_disposition_revision(item, expected_revision)
            if disposition.get("status") == "FALSE_POSITIVE" and status != "FALSE_POSITIVE" and item.get("mobileProducer"):
                raise ValueError("disposition_terminal")
            action = {"status": status, "actor": actor, "actedAtUs": action_time}
            if operation_id is not None:
                action.update(operationId=operation_id, requestDigest=request_digest)
            if note:
                action["note"] = str(note)[:1000]
            history.append(action)
            disposition.update({"status": status, "actor": actor, "actedAtUs": action_time, "history": history})
            item["disposition"] = disposition
            disposition_committed(item, revision, actor, status)
            # False positives are terminal for the current event and produce
            # one deterministic feedback entry per action.
            if status == "FALSE_POSITIVE":
                item["state"] = "ENDED"
                entry_id = "fp-" + hashlib.sha256(f"{event_id}\0{action_time}".encode()).hexdigest()[:24]
                raw_evidence = dict(item.get("evidence") or {})
                if evidence:
                    raw_evidence.update(deepcopy(dict(evidence)))
                feedback_evidence = _feedback_evidence(raw_evidence, screenshot, project_id, event_id)
                thresholds = effective_thresholds if effective_thresholds is not None else item.get("effectiveThresholds", {})
                detections = detection_results if detection_results is not None else item.get("detectionResults", item.get("detections", []))
                training = {
                    "entryId": entry_id,
                    "projectId": project_id,
                    "eventId": event_id,
                    "label": "false_positive",
                    **feedback_evidence,
                    "annotations": [],
                    "detectionResults": deepcopy(detections),
                    "effectiveThresholds": deepcopy(dict(thresholds or {})),
                    "thresholds": deepcopy(dict(thresholds or {})),
                    "sourceId": item.get("sourceId"),
                    "provenance": deepcopy(item.get("provenance")),
                    "model": deepcopy(item.get("model")),
                    "subjectKey": item.get("subjectKey"),
                    "capturedAtUs": item.get("confirmedAtUs", item.get("startedAtUs")),
                    "ruleId": item.get("ruleId"),
                    "ruleVersion": item.get("ruleVersion"),
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
                self._feedback[(project_id, entry_id)] = sanitise_training_entry(training)
                item["falsePositiveEntryId"] = entry_id
            self._events[key] = item
            return deepcopy(item)

    def feedback(self, project_id: str = DEFAULT_PROJECT_ID) -> list[dict[str, Any]]:
        if self._database is not None:
            with self._database.session() as session:
                rows = session.scalars(
                    select(FalsePositiveFeedbackRecord)
                    .where(FalsePositiveFeedbackRecord.project_id == project_id)
                    .order_by(FalsePositiveFeedbackRecord.created_at)
                ).all()
                return [public_training_entry(row.payload, project_id) for row in rows]
        with self._lock:
            return [
                public_training_entry(value, project_id)
                for (pid, _), value in self._feedback.items()
                if pid == project_id
            ]

    def acknowledge(self, event_id: str, actor: str, *, acted_at_us: Any = None,
                    note: str | None = None, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        return self.dispose(
            event_id, "ACKNOWLEDGED", actor, acted_at_us=acted_at_us,
            note=note, project_id=project_id,
        )

    def mark_false_positive(self, event_id: str, actor: str, **kwargs: Any) -> dict[str, Any]:
        return self.dispose(event_id, "FALSE_POSITIVE", actor, **kwargs)

    def export_json(self, project_id: str = DEFAULT_PROJECT_ID) -> bytes:
        with self._lock:
            entries = self.feedback(project_id)
            payload = {"format": "aiyolo-false-positive-v1", "entries": entries, "trainingEntries": entries}
        return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")

    def export_false_positives(self, project_id: str = DEFAULT_PROJECT_ID) -> list[dict[str, Any]]:
        """Return sanitized entries for callers that do not need a byte stream."""
        return self.feedback(project_id)

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
