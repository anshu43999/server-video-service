"""Audited, resumable retention for explicitly referenced alert evidence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from ..database import AlertEventRecord, PlatformAuditEventRecord
from ..alert_evidence import AlertEvidenceStore


DEFAULT_RETENTION_DAYS = 90
MAX_SAMPLE_RETENTION_DAYS = 365
DELETE_GRACE = timedelta(hours=24)


def _references(payload: dict[str, Any]):
    evidence = payload.get("evidence") or {}
    for evidence_type in ("thumbnail", "original"):
        versions = evidence.get(evidence_type) or {}
        if isinstance(versions, dict):
            for version, reference in versions.items():
                if isinstance(reference, dict):
                    yield evidence_type, str(version), reference


def _dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def cleanup_alert_evidence(database, store: AlertEvidenceStore, *, apply: bool = False,
                           batch_size: int = 100, now: datetime | None = None,
                           after: tuple[str, str] | None = None,
                           retention_days: int = DEFAULT_RETENTION_DAYS,
                           grace_hours: int = 24) -> dict[str, Any]:
    """Mark expired references, then after grace recheck and delete in bounded batches.

    Unknown/legacy references without upload timestamps and unreferenced bucket
    objects are intentionally excluded; this job never sweeps MinIO by prefix.
    """
    if not database.enabled:
        raise ValueError("evidence retention requires a persistent database")
    if not store.enabled:
        raise ValueError("evidence retention requires configured MinIO storage")
    if not 1 <= batch_size <= 500:
        raise ValueError("batch_size must be between 1 and 500")
    if not 1 <= retention_days <= 365 or not 1 <= grace_hours <= 168:
        raise ValueError("retention_days must be 1..365 and grace_hours must be 1..168")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    now = now.astimezone(timezone.utc)
    stats = {"mode": "apply" if apply else "dry-run", "scanned": 0, "eligible": 0,
             "marked": 0, "deleted": 0, "retained": 0, "failed": 0,
             "skippedUnknownAge": 0, "batchSize": batch_size, "nextAfter": None,
             "retentionDays": retention_days, "graceHours": grace_hours}

    with database.session() as session:
        query = select(AlertEventRecord).order_by(
            AlertEventRecord.project_id, AlertEventRecord.event_id
        )
        if after:
            from sqlalchemy import or_, and_
            query = query.where(or_(
                AlertEventRecord.project_id > after[0],
                and_(AlertEventRecord.project_id == after[0], AlertEventRecord.event_id > after[1]),
            ))
        rows = session.scalars(query.limit(batch_size + 1)).all()
        has_more = len(rows) > batch_size
        rows = rows[:batch_size]
        stats["scanned"] = len(rows)
        for row in rows:
            payload = deepcopy(row.payload or {})
            changed = False
            for evidence_type, version, ref in _references(payload):
                obj = ref.get("objectStorage") or {}
                if obj.get("provider") != "minio" or obj.get("bucket") != store.bucket:
                    stats["retained"] += 1
                    continue
                uploaded = _dt(ref.get("uploadedAt"))
                if uploaded is None:
                    stats["skippedUnknownAge"] += 1
                    continue
                state = ref.get("retentionState", "ACTIVE")
                hold_until = _dt(ref.get("retentionUntil"))
                if hold_until and (hold_until > uploaded + timedelta(days=MAX_SAMPLE_RETENTION_DAYS)
                                   or hold_until > now):
                    stats["retained"] += 1
                    continue
                expires = uploaded + timedelta(days=retention_days)
                if now < expires:
                    stats["retained"] += 1
                    continue
                stats["eligible"] += 1
                if state == "ACTIVE":
                    stats["marked"] += 1
                    if apply:
                        ref["retentionState"] = "DELETE_PENDING"
                        ref["deleteAfter"] = (now + timedelta(hours=grace_hours)).isoformat()
                        changed = True
                    continue
                delete_after = _dt(ref.get("deleteAfter"))
                if state != "DELETE_PENDING" or delete_after is None or delete_after > now:
                    stats["retained"] += 1
                    continue
                if not apply:
                    stats["deleted"] += 1
                    continue

                # Re-fetch and lock the owning row immediately before deleting.
                locked = session.scalar(select(AlertEventRecord).where(
                    AlertEventRecord.project_id == row.project_id,
                    AlertEventRecord.event_id == row.event_id,
                ).with_for_update().execution_options(populate_existing=True))
                if locked is None:
                    stats["retained"] += 1
                    continue
                live = deepcopy(locked.payload or {})
                live_ref = ((live.get("evidence") or {}).get(evidence_type) or {}).get(version)
                if not isinstance(live_ref, dict) or live_ref.get("retentionState") != "DELETE_PENDING":
                    stats["retained"] += 1
                    continue
                # Never delete an object while any current event reference points at it.
                key = obj.get("objectKey")
                reference_count = 0
                all_rows = session.scalars(select(AlertEventRecord)).all()
                for other in all_rows:
                    for _, _, other_ref in _references(other.payload or {}):
                        other_obj = other_ref.get("objectStorage") or {}
                        if other_obj.get("bucket") == store.bucket and other_obj.get("objectKey") == key:
                            reference_count += 1
                if reference_count != 1:
                    stats["retained"] += 1
                    continue
                try:
                    store.remove_tiered(obj)
                except Exception:
                    stats["failed"] += 1
                    continue
                live_ref["retentionState"] = "DELETED"
                live_ref["deletedAt"] = now.isoformat()
                live_ref.pop("objectStorage", None)
                locked.payload = live
                stats["deleted"] += 1
                changed = False
            if changed and row.payload != payload:
                row.payload = payload
        if has_more and rows:
            stats["nextAfter"] = [rows[-1].project_id, rows[-1].event_id]
        if apply and (stats["marked"] or stats["deleted"] or stats["failed"]):
            session.add(PlatformAuditEventRecord(
                audit_id=str(uuid4()), occurred_at=now, action="alert.evidence.retention",
                target_type="alert_evidence", target_id=None, outcome="SUCCESS" if not stats["failed"] else "FAILED",
                failure_code="object_delete_failed" if stats["failed"] else None,
                change_summary={key: value for key, value in stats.items() if key != "mode"} | {"mode": "apply"},
                request_id=str(uuid4()),
            ))
    return stats


def retain_alert_evidence(database, *, project_id: str, event_id: str,
                          evidence_type: str, content_version: int,
                          until: datetime, actor: str, now: datetime | None = None) -> dict[str, Any]:
    """Apply an explicit, audited sample-retention marker (maximum 365 days)."""
    if not database.enabled:
        raise ValueError("evidence retention requires a persistent database")
    if evidence_type not in {"thumbnail", "original"} or content_version < 1:
        raise ValueError("invalid evidence identity")
    if not actor.strip() or until.tzinfo is None:
        raise ValueError("actor and timezone-aware until are required")
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    until = until.astimezone(timezone.utc)
    with database.session() as session:
        row = session.scalar(select(AlertEventRecord).where(
            AlertEventRecord.project_id == project_id,
            AlertEventRecord.event_id == event_id,
        ).with_for_update())
        if row is None:
            raise KeyError(event_id)
        payload = deepcopy(row.payload or {})
        ref = (((payload.get("evidence") or {}).get(evidence_type) or {})
               .get(str(content_version)))
        if not isinstance(ref, dict):
            raise KeyError(str(content_version))
        uploaded = _dt(ref.get("uploadedAt"))
        if uploaded is None or until <= now or until > uploaded + timedelta(days=MAX_SAMPLE_RETENTION_DAYS):
            raise ValueError("retention marker must be future-dated and no later than 365 days after upload")
        ref["retentionUntil"] = until.isoformat()
        ref["retentionMarkedAt"] = now.isoformat()
        ref["retentionMarkedBy"] = actor[:128]
        if ref.get("retentionState") == "DELETE_PENDING":
            ref["retentionState"] = "ACTIVE"
            ref.pop("deleteAfter", None)
        row.payload = payload
        session.add(PlatformAuditEventRecord(
            audit_id=str(uuid4()), occurred_at=now, action="alert.evidence.retain",
            target_type="alert_evidence", target_id=f"{project_id}:{event_id}:{evidence_type}:{content_version}",
            outcome="SUCCESS", change_summary={"until": until.isoformat(), "actor": actor[:128]},
            request_id=str(uuid4()),
        ))
    return {"projectId": project_id, "eventId": event_id, "evidenceType": evidence_type,
            "contentVersion": content_version, "retentionUntil": until.isoformat()}
