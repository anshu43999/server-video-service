"""One system catalog and immutable releases shared by all authorized projects."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock

from sqlalchemy import select

from .alert_advice_knowledge import KnowledgeConflict, KnowledgeNotFound, KnowledgeError, _text
from .system_knowledge_draft import SystemKnowledgeDraft
from .database import SystemKnowledgeCatalogRecord, SystemKnowledgeReleaseRecord
from .project_business import audit_change


def initial_knowledge():
    store = SystemKnowledgeDraft()
    for raw in json.loads((Path(__file__).parent / "data/alert_knowledge_v1.json").read_text(encoding="utf-8")):
        raw = deepcopy(raw)
        entry_id = raw.pop("entryId")
        alert_type = raw.pop("alertTypeId")
        category = raw.pop("recognitionCategoryId")
        status = raw.pop("status", "ACTIVE")
        store.create(entry_id, alert_type, category, raw, "system:initial-v1", status=status)
    return store.snapshot()


def initial_release(payload):
    return {"version": 1, "catalogRevision": 1, "notes": "PPE 模型初始模拟资料", "publishedBy": "system:initial-v1",
            "publishedAt": datetime.now(timezone.utc).isoformat(), "entries": deepcopy(payload["entries"])}


class SystemKnowledgeStore:
    def __init__(self, database=None):
        self.database = database
        self._lock = RLock()
        self._payload = initial_knowledge()
        self._revision = 1
        self._releases = {1: initial_release(self._payload)}

    @property
    def persistent(self):
        return self.database is not None and self.database.enabled

    def catalog(self):
        if self.persistent:
            with self.database.session() as session:
                row = session.get(SystemKnowledgeCatalogRecord, 1)
                return {"revision": row.revision, **self._mark_system(deepcopy(row.payload))}
        with self._lock:
            return {"revision": self._revision, **self._mark_system(deepcopy(self._payload))}

    @staticmethod
    def _mark_system(payload):
        for entry in payload["entries"]:
            entry.update({"origin": "SYSTEM", "systemVersion": None})
        return payload

    def versions(self):
        if self.persistent:
            with self.database.session() as session:
                releases = [deepcopy(row.snapshot) for row in session.scalars(select(SystemKnowledgeReleaseRecord).order_by(SystemKnowledgeReleaseRecord.version)).all()]
        else:
            with self._lock:
                releases = deepcopy(list(self._releases.values()))
        return [{key: value for key, value in release.items() if key != "entries"} | {"entryCount": len(release["entries"])} for release in releases]

    def release(self, version, session=None):
        if self.persistent:
            if session is None:
                with self.database.session() as own:
                    return self.release(version, own)
            row = session.get(SystemKnowledgeReleaseRecord, version)
            if row is None:
                raise KnowledgeNotFound("system version was not found")
            return deepcopy(row.snapshot)
        with self._lock:
            if version not in self._releases:
                raise KnowledgeNotFound("system version was not found")
            return deepcopy(self._releases[version])

    def latest_release(self):
        """Read one complete published snapshot; never expose unpublished drafts."""
        if self.persistent:
            with self.database.session() as session:
                row = session.scalar(select(SystemKnowledgeReleaseRecord).order_by(
                    SystemKnowledgeReleaseRecord.version.desc()).limit(1))
                if row is None:
                    raise KnowledgeNotFound("no system knowledge version has been published")
                return deepcopy(row.snapshot)
        with self._lock:
            return deepcopy(self._releases[max(self._releases)])

    def published(self, project_id):
        release = self.latest_release()
        for item in release["entries"]:
            # projectId is authorization/response context, not ownership or a version pin.
            item.update({"sourceEntryId": item["entryId"], "entryId": "system:" + item["entryId"],
                         "projectId": project_id, "origin": "SYSTEM", "systemVersion": release["version"]})
        return release

    def mutate(self, operation, actor, *, context=None, request_id=None, **kwargs):
        with self._lock:
            if self.persistent:
                with self.database.session() as session:
                    row = session.scalar(select(SystemKnowledgeCatalogRecord).where(SystemKnowledgeCatalogRecord.catalog_id == 1).with_for_update())
                    payload, result = self._mutate(row.payload, operation, actor,
                                                  {key: value for key, value in kwargs.items() if key not in {"context", "request_id"}})
                    before = {"revision": row.revision}
                    row.payload = payload
                    row.revision += 1
                    audit_change(session, context, request_id, "system_alert_knowledge." + operation, "system_alert_knowledge", result["entryId"], before, {"revision": row.revision, "entry": result})
                    return result
            payload, result = self._mutate(self._payload, operation, actor,
                                          {key: value for key, value in kwargs.items() if key not in {"context", "request_id"}})
            before = {"revision": self._revision}
            self._payload = payload
            self._revision += 1
            audit_change(None, context, request_id, "system_alert_knowledge." + operation, "system_alert_knowledge", result["entryId"], before, {"revision": self._revision, "entry": result})
            result.update({"origin": "SYSTEM", "systemVersion": None})
            return result

    @staticmethod
    def _mutate(payload, operation, actor, kwargs):
        if operation not in {"create", "replace", "set_status"}:
            raise KnowledgeError("unsupported system draft operation")
        draft = SystemKnowledgeDraft(payload)
        result = getattr(draft, operation)(actor=actor, **kwargs)
        return draft.snapshot(), result

    def publish(self, expected_revision, notes, actor, *, context=None, request_id=None):
        notes = _text(notes, "notes", 2000)
        actor = _text(actor, "actor", 128)
        with self._lock:
            if self.persistent:
                with self.database.session() as session:
                    row = session.scalar(select(SystemKnowledgeCatalogRecord).where(SystemKnowledgeCatalogRecord.catalog_id == 1).with_for_update())
                    if row.revision != expected_revision:
                        raise KnowledgeConflict("system drafts changed; review before publishing")
                    latest = session.scalar(select(SystemKnowledgeReleaseRecord.version).order_by(SystemKnowledgeReleaseRecord.version.desc()).limit(1))
                    release = self._publication(latest + 1, row.revision, row.payload, notes, actor)
                    session.add(SystemKnowledgeReleaseRecord(version=release["version"], snapshot=release))
                    # Publication itself consumes the CAS revision, so duplicate/stale publication fails.
                    row.revision += 1
                    audit_change(session, context, request_id, "system_alert_knowledge.publish", "system_knowledge_release", str(release["version"]), None, {key: value for key, value in release.items() if key != "entries"})
                    return deepcopy(release)
            if self._revision != expected_revision:
                raise KnowledgeConflict("system drafts changed; review before publishing")
            release = self._publication(max(self._releases) + 1, self._revision, self._payload, notes, actor)
            audit_change(None, context, request_id, "system_alert_knowledge.publish", "system_knowledge_release", str(release["version"]), None, {key: value for key, value in release.items() if key != "entries"})
            self._releases[release["version"]] = release
            self._revision += 1
            return deepcopy(release)

    @staticmethod
    def _publication(version, revision, payload, notes, actor):
        return {"version": version, "catalogRevision": revision, "notes": notes, "publishedBy": actor,
                "publishedAt": datetime.now(timezone.utc).isoformat(), "entries": deepcopy(payload["entries"])}
