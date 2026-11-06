"""System drafts, immutable releases and explicitly pinned project bases."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock

from sqlalchemy import select

from .alert_advice_knowledge import AlertAdviceKnowledgeStore, KnowledgeConflict, KnowledgeNotFound, KnowledgeError, _text
from .database import SystemKnowledgeCatalogRecord, SystemKnowledgeReleaseRecord, ProjectKnowledgeBaseRecord
from .project_business import audit_change, lock_project


def initial_knowledge():
    store = AlertAdviceKnowledgeStore()
    for raw in json.loads((Path(__file__).parent / "data/alert_knowledge_v1.json").read_text(encoding="utf-8")):
        raw = deepcopy(raw)
        entry_id = raw.pop("entryId")
        alert_type = raw.pop("alertTypeId")
        category = raw.pop("recognitionCategoryId")
        status = raw.pop("status", "ACTIVE")
        store.create("system", entry_id, alert_type, category, raw, "system:initial-v1", status=status)
    entries = store.list("system")
    return {"entries": entries, "history": {entry["entryId"]: store.revisions("system", entry["entryId"]) for entry in entries}}


def initial_release(payload):
    return {"version": 1, "catalogRevision": 1, "notes": "PPE 模型初始模拟资料", "publishedBy": "system:initial-v1",
            "publishedAt": datetime.now(timezone.utc).isoformat(), "entries": deepcopy(payload["entries"])}


def pin_new_project(session, project_id):
    # Called in the project creation transaction, serialized with publication.
    catalog = session.scalar(select(SystemKnowledgeCatalogRecord).where(SystemKnowledgeCatalogRecord.catalog_id == 1).with_for_update())
    if catalog is None:
        raise RuntimeError("system knowledge schema must be migrated before creating projects")
    version = session.scalar(select(SystemKnowledgeReleaseRecord.version).order_by(SystemKnowledgeReleaseRecord.version.desc()).limit(1))
    session.add(ProjectKnowledgeBaseRecord(project_id=project_id, version=version, revision=1))


class SystemKnowledgeStore:
    def __init__(self, database=None):
        self.database = database
        self._lock = RLock()
        self._payload = initial_knowledge()
        self._revision = 1
        self._releases = {1: initial_release(self._payload)}
        self._bindings = {}

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

    def binding(self, project_id, session=None):
        if self.persistent:
            if session is None:
                with self.database.session() as own:
                    return self.binding(project_id, own)
            row = session.get(ProjectKnowledgeBaseRecord, project_id)
            if row is None:
                raise KnowledgeNotFound("project knowledge base is not initialized")
            return {"version": row.version, "revision": row.revision}
        with self._lock:
            return deepcopy(self._bindings.get(project_id, {"version": 1, "revision": 1}))

    def pin_new_memory_project(self, project_id):
        with self._lock:
            self._bindings[project_id] = {"version": max(self._releases), "revision": 1}

    def inherited(self, project_id, session=None):
        binding = self.binding(project_id, session)
        items = self.release(binding["version"], session)["entries"]
        for item in items:
            item.update({"sourceEntryId": item["entryId"], "entryId": "system:" + item["entryId"], "projectId": project_id,
                         "origin": "SYSTEM", "systemVersion": binding["version"], "baseRevision": binding["revision"]})
        return items

    def adopt(self, project_id, version, expected_revision, actor, *, context=None, request_id=None):
        with self._lock:
            if self.persistent:
                with self.database.session() as session:
                    lock_project(session, project_id)
                    self.release(version, session)
                    before = self.binding(project_id, session)
                    if before["revision"] != expected_revision:
                        raise KnowledgeConflict("project base changed; refresh before upgrading")
                    if version <= before["version"]:
                        raise KnowledgeError("project base can only upgrade to a newer published version")
                    row = session.get(ProjectKnowledgeBaseRecord, project_id)
                    row.version = version
                    row.revision += 1
                    after = {"version": row.version, "revision": row.revision}
                    audit_change(session, context, request_id, "alert_advice_base.upgrade", "alert_advice_base", project_id, before, after)
                    return after
            self.release(version)
            before = self.binding(project_id)
            if before["revision"] != expected_revision:
                raise KnowledgeConflict("project base changed; refresh before upgrading")
            if version <= before["version"]:
                raise KnowledgeError("project base can only upgrade to a newer published version")
            after = {"version": version, "revision": before["revision"] + 1}
            audit_change(None, context, request_id, "alert_advice_base.upgrade", "alert_advice_base", project_id, before, after)
            self._bindings[project_id] = after
            return deepcopy(after)

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
        # Reuse the exact validation and revision semantics of project materials.
        store = AlertAdviceKnowledgeStore()
        store._entries = {("system", entry["entryId"]): deepcopy(entry) for entry in payload["entries"]}
        store._revisions = {("system", key): deepcopy(value) for key, value in payload["history"].items()}
        result = getattr(store, operation)("system", actor=actor, **kwargs)
        return {"entries": store.list("system"), "history": {key[1]: value for key, value in store._revisions.items()}}, result

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
