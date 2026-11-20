"""System-only draft editing; no project repository, database, or audit side effects."""
from copy import deepcopy
from datetime import datetime, timezone
import re

from .alert_advice_knowledge import (
    ACTIVE, INACTIVE, KnowledgeConflict, KnowledgeError, KnowledgeMatchConflict,
    KnowledgeNotFound, _text, normalize_match_key, validate_payload,
)


class SystemKnowledgeDraft:
    """A private copy edited under SystemKnowledgeStore's catalog lock/transaction."""

    def __init__(self, payload=None):
        payload = deepcopy(payload) if payload is not None else {"entries": [], "history": {}}
        self.entries = {entry["entryId"]: entry for entry in payload["entries"]}
        self.history = payload["history"]

    def snapshot(self):
        return deepcopy({"entries": [self.entries[key] for key in sorted(self.entries)],
                         "history": self.history})

    def create(self, entry_id, alert_type_id, recognition_category_id, payload, actor, *, status=ACTIVE):
        if not isinstance(entry_id, str) or len(entry_id) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", entry_id):
            raise KnowledgeError("entryId is invalid")
        alert_type_id, recognition_category_id = normalize_match_key(alert_type_id, recognition_category_id)
        payload = validate_payload(payload)
        actor = _text(actor, "actor", 128)
        if status not in {ACTIVE, INACTIVE}:
            raise KnowledgeError("status is invalid")
        key = {"alertTypeId": alert_type_id, "recognitionCategoryId": recognition_category_id}
        if entry_id in self.entries or any(item["matchKey"] == key for item in self.entries.values()):
            raise KnowledgeMatchConflict("entry id or match key already exists")
        now = datetime.now(timezone.utc).isoformat()
        # Preserve the existing serialized system-draft format for releases/migrations.
        entry = {**payload, "entryId": entry_id, "projectId": "system", "matchKey": key,
                 "status": status, "revision": 1, "createdBy": actor, "updatedBy": actor,
                 "createdAt": now, "updatedAt": now}
        self.entries[entry_id] = entry
        self.history[entry_id] = []
        return self._record(entry, "CREATE")

    def replace(self, entry_id, payload, actor, expected_revision, *, status=None):
        payload = validate_payload(payload)
        actor = _text(actor, "actor", 128)
        current = self._get(entry_id)
        if current["revision"] != expected_revision:
            raise KnowledgeConflict("knowledge revision changed")
        next_status = current["status"] if status is None else status
        if next_status not in {ACTIVE, INACTIVE}:
            raise KnowledgeError("status is invalid")
        action = "UPDATE" if next_status == current["status"] else ("ACTIVATE" if next_status == ACTIVE else "DEACTIVATE")
        entry = {**payload, **{key: current[key] for key in ("entryId", "projectId", "matchKey", "createdBy", "createdAt")},
                 "status": next_status, "revision": expected_revision + 1, "updatedBy": actor,
                 "updatedAt": datetime.now(timezone.utc).isoformat()}
        self.entries[entry_id] = entry
        return self._record(entry, action)

    def set_status(self, entry_id, status, actor, expected_revision):
        entry = self._get(entry_id)
        payload = {key: entry[key] for key in ("title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType")}
        return self.replace(entry_id, payload, actor, expected_revision, status=status)

    def _get(self, entry_id):
        if entry_id not in self.entries:
            raise KnowledgeNotFound("system entry was not found")
        return self.entries[entry_id]

    def _record(self, entry, action):
        self.history[entry["entryId"]].append({
            "revision": entry["revision"], "action": action, "actor": entry["updatedBy"],
            "snapshot": deepcopy(entry), "createdAt": entry["updatedAt"],
        })
        return deepcopy(entry)
