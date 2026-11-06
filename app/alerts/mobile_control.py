"""Durable server-to-capture control; all mutations share the owning event lock."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ..database import AlertEventRecord, PlatformAuditEventRecord


def disposition_revision(item):
    return max(int(item.get("dispositionRevision", 0)),
               len((item.get("disposition") or {}).get("history") or []))


def check_disposition_revision(item, expected):
    current = disposition_revision(item)
    if (expected is not None and expected != current) or (item.get("mobileProducer") and expected is None):
        raise ValueError("disposition_revision_conflict")
    return current


def matching_producer(item, account_id, producer_id):
    return item.get("mobileProducer") == {"accountId": account_id, "producerId": producer_id}


def latest_original_requests(item):
    # JSONB object key order is not insertion order after a database restart.
    requests = item.get("_originalRequests", {}).values()
    return sorted(requests, key=lambda r: (r.get("requestSequence", 0),
                                          r.get("requestedAt", ""), r["requestId"]))[-1:]


def uploaded_original(item):
    versions = (item.get("evidence") or {}).get("original") or {}
    for version in sorted(versions, key=lambda v: int(v), reverse=True):
        ref = versions[version]
        if ref.get("retentionState", "ACTIVE") == "ACTIVE" and ref.get("objectStorage"):
            return {"contentVersion": int(version), "sha256": ref.get("sha256")}
    return None


def request_original(item, actor, reason, operation_id=None, digest=None):
    if item.get("origin") not in {"MOBILE_IMAGE", "MOBILE_CAMERA"}:
        raise ValueError("not_mobile_capture")
    operations = item.setdefault("_originalOperations", {})
    requests = item.setdefault("_originalRequests", {})
    if operation_id in operations:
        old = operations[operation_id]
        if old["digest"] != digest:
            raise ValueError("idempotency_conflict")
        return requests[old["requestId"]]
    pending = next((r for r in requests.values() if r["status"] == "PENDING"), None)
    if pending is None:
        pending = {"requestId": str(uuid4()), "reason": reason, "requestedBy": actor,
                   "requestedAt": datetime.now(timezone.utc).isoformat(), "status": "PENDING",
                   "requestSequence": len(requests) + 1}
        original = uploaded_original(item)
        if original:
            pending.update(status="UPLOADED", **original)
        elif not item.get("mobileProducer"):
            pending.update(status="UNAVAILABLE", unavailableReason="producer_unregistered")
        requests[pending["requestId"]] = pending
    if operation_id:
        operations[operation_id] = {"requestId": pending["requestId"], "digest": digest}
    return pending


def disposition_committed(item, revision, actor, status):
    item["dispositionRevision"] = revision + 1
    if status == "FALSE_POSITIVE" and item.get("origin") in {"MOBILE_IMAGE", "MOBILE_CAMERA"}:
        request_original(item, actor, "FALSE_POSITIVE")


class MobileAlertControlStore:
    def _control_mutation(self, event_id, project_id, mutate, *, audit_actor=None, audit_action=None):
        with self._lock:
            if self._database is not None:
                with self._database.session() as session:
                    row = session.scalar(select(AlertEventRecord).where(
                        AlertEventRecord.project_id == project_id,
                        AlertEventRecord.event_id == event_id).with_for_update())
                    if row is None:
                        raise KeyError(event_id)
                    item = self._row_mapping(session, row)
                    result = mutate(item)
                    self._apply_row(row, item)
                    if audit_action:
                        session.add(PlatformAuditEventRecord(
                            audit_id=str(uuid4()), occurred_at=datetime.now(timezone.utc),
                            action=audit_action, target_type="alert_event", target_id=event_id,
                            outcome="SUCCESS", change_summary={"projectId": project_id, "actor": audit_actor},
                            request_id=str(uuid4())))
                    return deepcopy(result)
            item = deepcopy(self._events[(project_id, event_id)])
            result = mutate(item)
            self._events[(project_id, event_id)] = item
            return deepcopy(result)

    def request_original(self, event_id, project_id, actor, expected_revision, operation_id, digest):
        def mutate(item):
            # Exact operation replay precedes CAS, including after later dispositions.
            if operation_id not in item.get("_originalOperations", {}):
                check_disposition_revision(item, expected_revision)
            request_original(item, actor, "DASHBOARD_REQUEST", operation_id, digest)
            return item
        return self._control_mutation(event_id, project_id, mutate, audit_actor=actor,
                                      audit_action="alert.evidence.request")

    def mobile_sync(self, project_id, account_id, captures):
        result = []
        for capture in captures:
            try:
                item = self.get(capture["eventId"], project_id)
            except KeyError:
                continue
            if matching_producer(item, account_id, capture["producerId"]):
                result.append({"eventId": item["eventId"], "projectId": project_id,
                               "disposition": item["disposition"],
                               "dispositionRevision": disposition_revision(item),
                               # At most one PENDING request exists. Returning the latest
                               # terminal result is enough for receipt-loss recovery; old
                               # completed attempts must not grow a mobile response forever.
                               "requests": latest_original_requests(item)})
        return result

    def original_receipt(self, event_id, project_id, account_id, request_id, receipt):
        def mutate(item):
            if not matching_producer(item, account_id, receipt["producerId"]):
                raise KeyError(event_id)
            request = item.get("_originalRequests", {}).get(request_id)
            if request is None:
                raise KeyError(request_id)
            outcome = {key: value for key, value in receipt.items() if value is not None and key != "producerId"}
            if request.get("receipt") is not None:
                if request["receipt"] != outcome:
                    raise ValueError("receipt_conflict")
                return request
            if request["status"] != "PENDING":
                if (request["status"] == receipt["status"] == "UPLOADED"
                        and request.get("contentVersion") == receipt["contentVersion"]
                        and request.get("sha256") == receipt["sha256"]):
                    return request
                raise ValueError("receipt_conflict")
            if receipt["status"] == "UPLOADED":
                reference = ((item.get("evidence") or {}).get("original") or {}).get(str(receipt["contentVersion"]))
                if (not reference or reference.get("retentionState", "ACTIVE") != "ACTIVE"
                        or not reference.get("objectStorage") or reference.get("sha256") != receipt["sha256"]):
                    raise ValueError("original_not_uploaded")
            request.update(status=receipt["status"], receipt=outcome,
                           completedAt=datetime.now(timezone.utc).isoformat())
            if receipt["status"] == "UNAVAILABLE":
                request["unavailableReason"] = receipt["reason"]
            else:
                request.update(contentVersion=receipt["contentVersion"], sha256=receipt["sha256"])
            return request
        return self._control_mutation(event_id, project_id, mutate, audit_actor=account_id,
                                      audit_action="alert.evidence.receipt")
