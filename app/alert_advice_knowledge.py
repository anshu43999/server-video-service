"""Versioned, project-scoped simulated knowledge for alert advice (M41)."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from threading import RLock
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .database import AlertAdviceKnowledgeEntryRecord, AlertAdviceKnowledgeRevisionRecord
from .project_business import audit_change, lock_project


ACTIVE = "ACTIVE"
INACTIVE = "INACTIVE"
MOCK_SOURCE = "MOCK_KNOWLEDGE_BASE"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class KnowledgeError(ValueError):
    code = "KNOWLEDGE_ENTRY_INVALID"


class KnowledgeConflict(KnowledgeError):
    code = "REVISION_CONFLICT"


class KnowledgeNotFound(KnowledgeError):
    code = "KNOWLEDGE_ENTRY_NOT_FOUND"


class KnowledgeMatchConflict(KnowledgeError):
    code = "ACTIVE_MATCH_KEY_CONFLICT"


def normalize_match_value(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeError(f"{field} must not be blank")
    normalized = value.strip().upper()
    if len(normalized) > 128:
        raise KnowledgeError(f"{field} exceeds 128 characters")
    return normalized


def normalize_match_key(alert_type_id: str, recognition_category_id: str) -> tuple[str, str]:
    return (
        normalize_match_value(alert_type_id, "alertTypeId"),
        normalize_match_value(recognition_category_id, "recognitionCategoryId"),
    )


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeError(f"{field} must not be blank")
    text = value.strip()
    if len(text) > maximum:
        raise KnowledgeError(f"{field} exceeds {maximum} characters")
    return text


def validate_payload(value: dict) -> dict:
    if not isinstance(value, dict):
        raise KnowledgeError("knowledge payload must be an object")
    allowed = {"title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType"}
    if set(value) - allowed:
        raise KnowledgeError("knowledge payload contains unsupported fields")
    advice = value.get("adviceTemplate")
    if not isinstance(advice, dict) or set(advice) - {"title", "steps", "cautions"}:
        raise KnowledgeError("adviceTemplate is invalid")
    steps = advice.get("steps")
    cautions = advice.get("cautions", [])
    if not isinstance(steps, list) or not isinstance(cautions, list):
        raise KnowledgeError("advice steps and cautions must be arrays")
    normalized_steps = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or set(step) != {"stepId", "order", "title", "instruction"}:
            raise KnowledgeError("advice step fields are invalid")
        if not isinstance(step["order"], int) or isinstance(step["order"], bool) or step["order"] != index:
            raise KnowledgeError("advice step order must be contiguous from one")
        normalized_steps.append({
            "stepId": _text(step["stepId"], "stepId", 128), "order": index,
            "title": _text(step["title"], "step title", 200),
            "instruction": _text(step["instruction"], "step instruction", 2000),
        })
    if not all(isinstance(item, str) and item.strip() and len(item.strip()) <= 1000 for item in cautions):
        raise KnowledgeError("cautions contain invalid values")
    references = value.get("references")
    if not isinstance(references, list) or not references:
        raise KnowledgeError("at least one policy reference is required")
    normalized_references = []
    required = {"referenceId", "documentTitle", "documentVersion", "excerpt", "sourceName", "sourceType"}
    optional = {"documentNumber", "chapter", "clauseId", "effectiveDate"}
    for reference in references:
        if not isinstance(reference, dict) or not required.issubset(reference) or set(reference) - required - optional:
            raise KnowledgeError("policy reference fields are invalid")
        if reference["sourceType"] != MOCK_SOURCE:
            raise KnowledgeError("M41 knowledge references must be simulated")
        item = {
            "referenceId": _text(reference["referenceId"], "referenceId", 128),
            "documentTitle": _text(reference["documentTitle"], "documentTitle", 300),
            "documentVersion": _text(reference["documentVersion"], "documentVersion", 128),
            "excerpt": _text(reference["excerpt"], "excerpt", 5000),
            "sourceName": _text(reference["sourceName"], "sourceName", 300),
            "sourceType": MOCK_SOURCE,
        }
        for field, maximum in (("documentNumber", 128), ("chapter", 300), ("clauseId", 128), ("effectiveDate", 32)):
            raw = reference.get(field)
            item[field] = None if raw is None else _text(raw, field, maximum)
        normalized_references.append(item)
    return {
        "title": _text(value.get("title"), "title", 300),
        "riskDescription": _text(value.get("riskDescription"), "riskDescription", 2000),
        "adviceTemplate": {
            "title": _text(advice.get("title"), "advice title", 300),
            "steps": normalized_steps,
            "cautions": [item.strip() for item in cautions],
        },
        "references": normalized_references,
        "applicability": _text(value.get("applicability"), "applicability", 2000),
        "sourceType": MOCK_SOURCE,
    }


def helmet_mock_seed() -> dict:
    return {
        "entryId": "mock-ppe-no-helmet-head",
        "alertTypeId": "PPE_NO_HELMET",
        "recognitionCategoryId": "HEAD",
        "status": ACTIVE,
        "payload": {
            "title": "未佩戴安全帽处置建议（模拟）",
            "riskDescription": "人员在指定作业区域未佩戴安全帽，可能暴露于坠物或碰撞风险。",
            "adviceTemplate": {
                "title": "未佩戴安全帽处置建议（模拟）",
                "steps": [
                    {"stepId": "pause-work", "order": 1, "title": "提醒并暂停相关作业", "instruction": "请现场人员先离开可能存在坠物或碰撞风险的作业区域。"},
                    {"stepId": "wear-helmet", "order": 2, "title": "佩戴合规安全帽", "instruction": "按现场要求正确佩戴并检查帽带等防护部件。"},
                    {"stepId": "review", "order": 3, "title": "复查并记录结果", "instruction": "确认防护措施落实后恢复作业，并按现场流程记录处理情况。"},
                ],
                "cautions": ["请结合现场条件和适用制度核实；本建议不构成违规认定。"],
            },
            "references": [{
                "referenceId": "mock-ppe-management-v1", "documentTitle": "个人防护用品管理制度（模拟资料）",
                "documentNumber": None, "documentVersion": "demo-v1", "chapter": None,
                "clauseId": "模拟条款 PPE-01", "excerpt": "进入指定作业区域时，应按现场要求正确佩戴适用的个人防护用品。",
                "sourceName": "AI YOLO 演示模拟知识库", "sourceType": MOCK_SOURCE, "effectiveDate": None,
            }],
            "applicability": "仅用于 PPE_NO_HELMET + HEAD 精确匹配的演示告警。",
            "sourceType": MOCK_SOURCE,
        },
    }


class AlertAdviceKnowledgeStore:
    def __init__(self, database=None, *, system=None):
        self.database = database
        self.system = system
        self._lock = RLock()
        self._entries: dict[tuple[str, str], dict] = {}
        self._revisions: dict[tuple[str, str], list[dict]] = {}

    @property
    def persistent(self):
        return self.database is not None and self.database.enabled

    @staticmethod
    def _entry_id(value):
        if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) or len(value) > 128:
            raise KnowledgeError("entryId is invalid")
        return value

    @staticmethod
    def _public(row):
        result = deepcopy(row.payload)
        result.update({
            "entryId": row.entry_id, "projectId": row.project_id,
            "matchKey": {"alertTypeId": row.alert_type_id, "recognitionCategoryId": row.recognition_category_id},
            "status": row.status, "revision": row.revision,
            "createdBy": row.created_by, "updatedBy": row.updated_by,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
            "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        })
        return result

    @staticmethod
    def _memory_public(row):
        return deepcopy(row)

    def create(self, project_id, entry_id, alert_type_id, recognition_category_id, payload, actor, *, status=ACTIVE,
               context=None, request_id=None, inherited_entry=None, expected_base_revision=None):
        entry_id = self._entry_id(entry_id)
        alert_type_id, recognition_category_id = normalize_match_key(alert_type_id, recognition_category_id)
        payload = validate_payload(payload)
        actor = _text(actor, "actor", 128)
        if status not in {ACTIVE, INACTIVE}:
            raise KnowledgeError("status is invalid")
        with self._lock:
            if self.system is not None and inherited_entry is None:
                inherited = self.system.inherited(project_id)
                if any(item["matchKey"] == {"alertTypeId": alert_type_id, "recognitionCategoryId": recognition_category_id}
                       for item in inherited):
                    raise KnowledgeMatchConflict("an inherited exact match must be explicitly overridden")
            if self.persistent:
                try:
                    with self.database.session() as session:
                        lock_project(session, project_id)
                        self._check_override(project_id, inherited_entry, expected_base_revision, session)
                        row = AlertAdviceKnowledgeEntryRecord(
                            project_id=project_id, entry_id=entry_id, alert_type_id=alert_type_id,
                            recognition_category_id=recognition_category_id, status=status, revision=1,
                            payload=deepcopy(payload), created_by=actor, updated_by=actor,
                        )
                        session.add(row); session.flush()
                        snapshot = self._public(row)
                        session.add(AlertAdviceKnowledgeRevisionRecord(
                            project_id=project_id, entry_id=entry_id, revision=1,
                            action="CREATE", actor=actor, snapshot=deepcopy(snapshot),
                        ))
                        audit_change(session, context, request_id, "alert_advice_knowledge.create",
                                     "alert_advice_knowledge", entry_id, None, snapshot)
                        return snapshot
                except IntegrityError as exc:
                    raise KnowledgeMatchConflict("entry id or match key already exists") from exc
            self._check_override(project_id, inherited_entry, expected_base_revision)
            now = datetime.now(timezone.utc).isoformat()
            if (project_id, entry_id) in self._entries or any(
                item["projectId"] == project_id and item["matchKey"] == {"alertTypeId": alert_type_id, "recognitionCategoryId": recognition_category_id}
                for item in self._entries.values()
            ):
                raise KnowledgeMatchConflict("entry id or match key already exists")
            row = {**deepcopy(payload), "entryId": entry_id, "projectId": project_id,
                   "matchKey": {"alertTypeId": alert_type_id, "recognitionCategoryId": recognition_category_id},
                   "status": status, "revision": 1, "createdBy": actor, "updatedBy": actor,
                   "createdAt": now, "updatedAt": now}
            self._entries[(project_id, entry_id)] = row
            self._revisions[(project_id, entry_id)] = [{
                "revision": 1, "action": "CREATE", "actor": actor,
                "snapshot": deepcopy(row), "createdAt": now,
            }]
            audit_change(None, context, request_id, "alert_advice_knowledge.create",
                         "alert_advice_knowledge", entry_id, None, row)
            return deepcopy(row)

    def get(self, project_id, entry_id):
        if self.system and any(item["entryId"] == entry_id for item in self.local_list(project_id)):
            return next(item for item in self.list(project_id) if item["entryId"] == entry_id)
        if self.system and entry_id.startswith("system:"):
            for item in self.system.inherited(project_id):
                if item["entryId"] == entry_id:
                    return item
            raise KnowledgeNotFound("inherited entry was overridden or was not found")
        if self.persistent:
            with self.database.session() as session:
                row = session.get(AlertAdviceKnowledgeEntryRecord, (project_id, entry_id))
                if row is None:
                    raise KnowledgeNotFound("knowledge entry was not found")
                return self._public(row)
        try:
            return deepcopy(self._entries[(project_id, entry_id)])
        except KeyError as exc:
            raise KnowledgeNotFound("knowledge entry was not found") from exc

    def local_list(self, project_id):
        if self.persistent:
            with self.database.session() as session:
                rows = session.scalars(select(AlertAdviceKnowledgeEntryRecord).where(
                    AlertAdviceKnowledgeEntryRecord.project_id == project_id
                ).order_by(AlertAdviceKnowledgeEntryRecord.entry_id)).all()
                return [self._public(row) for row in rows]
        return [deepcopy(value) for key, value in sorted(self._entries.items()) if key[0] == project_id]

    def list(self, project_id):
        local = self.local_list(project_id)
        if self.system is None:
            return local
        inherited = self.system.inherited(project_id)
        by_key = {(item["matchKey"]["alertTypeId"], item["matchKey"]["recognitionCategoryId"]): item for item in inherited}
        for item in local:
            key = (item["matchKey"]["alertTypeId"], item["matchKey"]["recognitionCategoryId"])
            item["origin"] = "PROJECT_OVERRIDE" if key in by_key else "PROJECT"
            item["systemVersion"] = inherited[0]["systemVersion"] if inherited else self.system.binding(project_id)["version"]
            by_key[key] = item
        return sorted(by_key.values(), key=lambda item: item["entryId"])

    def _check_override(self, project_id, entry, expected_revision, session=None):
        if entry is None:
            return
        if self.system.binding(project_id, session)["revision"] != expected_revision:
            raise KnowledgeConflict("project base changed; refresh before overriding")
        if not any(item["entryId"] == entry["entryId"] and item["revision"] == entry["revision"]
                   for item in self.system.inherited(project_id, session)):
            raise KnowledgeConflict("inherited material changed")

    def override(self, project_id, inherited_id, payload, status, actor, expected_base_revision, *, context=None, request_id=None):
        if self.system is None:
            raise KnowledgeNotFound("system inheritance is not configured")
        # Keep project pin and copy-on-write atomic even if an upgrade races this request.
        with self._lock, self.system._lock:
            entry = self.get(project_id, inherited_id)
            if entry.get("origin") != "SYSTEM":
                raise KnowledgeConflict("only inherited entries can be overridden")
            return self.create(project_id, "override-" + str(uuid4()), entry["matchKey"]["alertTypeId"],
                               entry["matchKey"]["recognitionCategoryId"], payload, actor, status=status,
                               context=context, request_id=request_id, inherited_entry=entry,
                               expected_base_revision=expected_base_revision)

    def find_active_exact(self, project_id, alert_type_id, recognition_category_id):
        alert_type_id, recognition_category_id = normalize_match_key(alert_type_id, recognition_category_id)
        for item in self.list(project_id):
            if item["status"] == ACTIVE and item["matchKey"] == {
                "alertTypeId": alert_type_id, "recognitionCategoryId": recognition_category_id,
            }:
                return item
        return None

    def replace(self, project_id, entry_id, payload, actor, expected_revision, *, status=None,
                context=None, request_id=None):
        payload = validate_payload(payload)
        actor = _text(actor, "actor", 128)
        with self._lock:
            if self.persistent:
                with self.database.session() as session:
                    lock_project(session, project_id)
                    row = session.scalar(select(AlertAdviceKnowledgeEntryRecord).where(
                        AlertAdviceKnowledgeEntryRecord.project_id == project_id,
                        AlertAdviceKnowledgeEntryRecord.entry_id == entry_id,
                    ).with_for_update())
                    if row is None:
                        raise KnowledgeNotFound("knowledge entry was not found")
                    if row.revision != expected_revision:
                        raise KnowledgeConflict("knowledge revision changed")
                    before = self._public(row)
                    next_status = row.status if status is None else status
                    if next_status not in {ACTIVE, INACTIVE}:
                        raise KnowledgeError("status is invalid")
                    action = "UPDATE" if next_status == row.status else ("ACTIVATE" if next_status == ACTIVE else "DEACTIVATE")
                    row.payload = deepcopy(payload); row.status = next_status
                    row.revision += 1; row.updated_by = actor; row.updated_at = datetime.now(timezone.utc)
                    session.flush(); snapshot = self._public(row)
                    session.add(AlertAdviceKnowledgeRevisionRecord(
                        project_id=project_id, entry_id=entry_id, revision=row.revision,
                        action=action, actor=actor, snapshot=deepcopy(snapshot),
                    ))
                    audit_change(session, context, request_id, f"alert_advice_knowledge.{action.lower()}",
                                 "alert_advice_knowledge", entry_id, before, snapshot)
                    return snapshot
            key = (project_id, entry_id)
            if key not in self._entries:
                raise KnowledgeNotFound("knowledge entry was not found")
            current = self._entries[key]
            if current["revision"] != expected_revision:
                raise KnowledgeConflict("knowledge revision changed")
            next_status = current["status"] if status is None else status
            if next_status not in {ACTIVE, INACTIVE}:
                raise KnowledgeError("status is invalid")
            action = "UPDATE" if next_status == current["status"] else ("ACTIVATE" if next_status == ACTIVE else "DEACTIVATE")
            updated = {**deepcopy(payload), **{key: current[key] for key in ("entryId", "projectId", "matchKey", "createdBy", "createdAt")},
                       "status": next_status, "revision": expected_revision + 1, "updatedBy": actor,
                       "updatedAt": datetime.now(timezone.utc).isoformat()}
            self._entries[key] = updated
            self._revisions[key].append({
                "revision": updated["revision"], "action": action, "actor": actor,
                "snapshot": deepcopy(updated), "createdAt": updated["updatedAt"],
            })
            audit_change(None, context, request_id, f"alert_advice_knowledge.{action.lower()}",
                         "alert_advice_knowledge", entry_id, current, updated)
            return deepcopy(updated)

    def set_status(self, project_id, entry_id, status, actor, expected_revision, *, context=None, request_id=None):
        current = self.get(project_id, entry_id)
        payload = {key: current[key] for key in ("title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType")}
        return self.replace(project_id, entry_id, payload, actor, expected_revision, status=status,
                            context=context, request_id=request_id)

    def revisions(self, project_id, entry_id):
        if self.system and not any(item["entryId"] == entry_id for item in self.local_list(project_id)) and entry_id.startswith("system:"):
            entry = self.get(project_id, entry_id)
            return [{"revision": entry["revision"], "action": "INHERIT", "actor": entry["updatedBy"],
                     "snapshot": entry, "createdAt": entry["updatedAt"], "systemVersion": entry["systemVersion"]}]
        if self.persistent:
            with self.database.session() as session:
                rows = session.scalars(select(AlertAdviceKnowledgeRevisionRecord).where(
                    AlertAdviceKnowledgeRevisionRecord.project_id == project_id,
                    AlertAdviceKnowledgeRevisionRecord.entry_id == entry_id,
                ).order_by(AlertAdviceKnowledgeRevisionRecord.revision)).all()
                if not rows:
                    self.get(project_id, entry_id)
                return [{"revision": row.revision, "action": row.action, "actor": row.actor,
                         "snapshot": deepcopy(row.snapshot), "createdAt": row.created_at.isoformat()} for row in rows]
        if (project_id, entry_id) not in self._revisions:
            raise KnowledgeNotFound("knowledge entry was not found")
        return deepcopy(self._revisions[(project_id, entry_id)])

    def ensure_mock_seed(self, project_id, actor="system:mock-seed"):
        seed = helmet_mock_seed()
        existing = self.find_active_exact(project_id, seed["alertTypeId"], seed["recognitionCategoryId"])
        if existing is not None:
            return existing, False
        try:
            created = self.create(project_id, seed["entryId"], seed["alertTypeId"], seed["recognitionCategoryId"], seed["payload"], actor)
            return created, True
        except KnowledgeMatchConflict:
            existing = self.find_active_exact(project_id, seed["alertTypeId"], seed["recognitionCategoryId"])
            if existing is None:
                raise
            return existing, False
