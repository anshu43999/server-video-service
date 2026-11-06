"""Runtime rule registry and capability-aware binding checks (M11-T07).

The evaluator remains pure; this module owns mutable configuration used by the
HTTP admin surface.  Every mutation increments ``ruleVersion`` and appends an
audit entry so a later event can be reproduced without restarting the process.
"""
from __future__ import annotations

import copy
import re
import threading
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import delete, select

from ..database import (
    AlertRuleAuditRecord,
    AlertRuleBindingRecord,
    AlertRuleRecord,
    DEFAULT_PROJECT_ID,
    DatabaseManager,
    database,
)
from .geometry import Roi, RoiGeometryError
from .observation import CAPABILITIES
from ..project_business import audit_change, lock_project, serialized

RULE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
OPS = {"PRESENCE", "IN_REGION", "LINE_CROSS", "DWELL", "COUNT", "AREA_RATIO", "RATE", "ABSENCE",
       "RELATION", "METRIC_THRESHOLD", "COMPOSITE"}
OPERATOR_REQUIREMENTS = {
    "IN_REGION": {"BOX"}, "COUNT": {"BOX"}, "AREA_RATIO": {"BOX"},
    "LINE_CROSS": {"BOX", "TRACK"}, "DWELL": {"BOX", "TRACK"},
}


class RuleValidationError(ValueError):
    def __init__(self, message: str, code: str = "RULE_INVALID"):
        super().__init__(message)
        self.code = code


class RuleConflict(RuleValidationError):
    def __init__(self):
        super().__init__("rule was changed by another operator", "revision_conflict")


class RuleRegistry:
    def __init__(self, database_manager: DatabaseManager | None = None) -> None:
        self._rules: dict[tuple[str, str], dict[str, Any]] = {}
        self._bindings: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self._audits: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._database = database_manager

    @staticmethod
    def _normalise(rule: Mapping[str, Any], existing: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = copy.deepcopy(dict(existing or {})); data.update(copy.deepcopy(dict(rule)))
        rid = str(data.get("ruleId", ""))
        if not RULE_ID.fullmatch(rid): raise RuleValidationError("ruleId must match [A-Za-z0-9_.-]{1,64}")
        op = str(data.get("operator", "")).upper()
        if op not in OPS: raise RuleValidationError(f"unsupported operator: {op}")
        subject = str(data.get("subjectKind", "track"))
        if subject not in {"track", "frame", "roi", "metric", "source"}: raise RuleValidationError("invalid subjectKind")
        requires = set(data.get("requires") or ()) | OPERATOR_REQUIREMENTS.get(op, set())
        unknown = requires - set(CAPABILITIES)
        if unknown: raise RuleValidationError(f"unknown capability: {sorted(unknown)}")
        data["ruleId"], data["operator"], data["subjectKind"] = rid, op, subject
        data["requires"] = sorted(requires)
        data["enabled"] = bool(data.get("enabled", True))
        data["thresholds"] = dict(data.get("thresholds") or {})
        data["ruleVersion"] = int(data.get("ruleVersion", 1))
        if data["ruleVersion"] < 1: raise RuleValidationError("ruleVersion must be positive")
        # Validate embedded ROI when supplied; geometry errors must be explicit.
        if data.get("roi") is not None:
            try: Roi.from_mapping(data["roi"])
            except (RoiGeometryError, KeyError, ValueError) as exc: raise RuleValidationError(str(exc), "ROI_GEOMETRY_INVALID") from exc
            shape = str(data["roi"].get("shape", ""))
            if shape == "POLYGON": requires.add("POLYGON_ROI")
            elif shape == "LINE": requires.add("LINE_ROI")
        data["requires"] = sorted(requires)
        return data

    @staticmethod
    def _audit(action: str, rid: str, version: int, actor: str = "admin", **extra: Any) -> dict[str, Any]:
        return {"action": action, "ruleId": rid, "ruleVersion": version, "actor": actor,
                "timestamp": datetime.now(timezone.utc).isoformat(), **copy.deepcopy(extra)}

    def list(self, project_id: str = DEFAULT_PROJECT_ID) -> list[dict[str, Any]]:
        if self._database is not None:
            with self._database.session() as session:
                rows = session.scalars(select(AlertRuleRecord).where(
                    AlertRuleRecord.project_id == project_id
                ).order_by(AlertRuleRecord.rule_id)).all()
                return [{**copy.deepcopy(dict(row.payload)), "projectId": row.project_id} for row in rows]
        with self._lock:
            return [copy.deepcopy(v) for (pid, _), v in self._rules.items() if pid == project_id]

    def get(self, rule_id: str, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        if self._database is not None:
            with self._database.session() as session:
                row = session.get(AlertRuleRecord, (project_id, rule_id))
                if row is None:
                    raise KeyError(rule_id)
                result = copy.deepcopy(dict(row.payload))
                result["projectId"] = row.project_id
                bindings = session.scalars(select(AlertRuleBindingRecord).where(
                    AlertRuleBindingRecord.project_id == project_id,
                    AlertRuleBindingRecord.rule_id == rule_id
                )).all()
                result["bindings"] = {item.source_id: copy.deepcopy(dict(item.payload)) for item in bindings}
                return result
        with self._lock:
            key = (project_id, rule_id)
            if key not in self._rules: raise KeyError(rule_id)
            result = copy.deepcopy(self._rules[key]); result["bindings"] = copy.deepcopy(self._bindings.get(key, {})); return result

    @serialized
    def upsert(self, rule: Mapping[str, Any], *, actor: str = "admin",
               project_id: str = DEFAULT_PROJECT_ID, expected_revision: int | None = None,
               context=None, request_id: str | None = None) -> dict[str, Any]:
        if self._database is not None:
            rid = str(rule.get("ruleId", ""))
            with self._database.session() as session:
                lock_project(session, project_id)
                old = session.scalar(select(AlertRuleRecord).where(
                    AlertRuleRecord.project_id == project_id,
                    AlertRuleRecord.rule_id == rid
                ).with_for_update())
                is_new = old is None
                before = copy.deepcopy(old.payload) if old else None
                if expected_revision is not None and expected_revision != (old.rule_version if old else 0):
                    raise RuleConflict()
                data = self._normalise(rule, old.payload if old else None)
                data["projectId"] = project_id
                data["ruleVersion"] = (old.rule_version if old else 0) + 1
                if old:
                    data["ruleVersion"] = old.rule_version + 1
                else:
                    old = AlertRuleRecord(project_id=project_id, rule_id=rid, rule_version=1, enabled=data["enabled"], payload={})
                    session.add(old)
                old.rule_version = data["ruleVersion"]
                old.enabled = data["enabled"]
                old.payload = copy.deepcopy(data)
                session.flush()
                audit = self._audit("create" if is_new else "update", rid, data["ruleVersion"], actor,
                                    projectId=project_id, requestId=request_id, before=before, after=data)
                session.add(AlertRuleAuditRecord(
                    project_id=project_id,
                    rule_id=rid, action=audit["action"], rule_version=data["ruleVersion"],
                    actor=actor, payload=audit,
                ))
                audit_change(session, context, request_id, "rule." + audit["action"], "rule", rid, before, data)
                return copy.deepcopy(data)
        with self._lock:
            rid = str(rule.get("ruleId", "")); key = (project_id, rid); old = self._rules.get(key)
            if expected_revision is not None and expected_revision != (int(old["ruleVersion"]) if old else 0):
                raise RuleConflict()
            data = self._normalise(rule, old)
            data["projectId"] = project_id
            data["ruleVersion"] = (int(old["ruleVersion"]) if old else 0) + 1
            self._rules[key] = data
            action = "update" if old else "create"
            self._audits.append(self._audit(action, rid, data["ruleVersion"], actor,
                                           projectId=project_id, requestId=request_id, before=old, after=data))
            audit_change(None, context, request_id, "rule." + action, "rule", rid, old, data)
            return copy.deepcopy(data)

    @serialized
    def delete(self, rule_id: str, *, actor: str = "admin", project_id: str = DEFAULT_PROJECT_ID,
               expected_revision: int | None = None, context=None, request_id: str | None = None) -> None:
        if self._database is not None:
            with self._database.session() as session:
                lock_project(session, project_id)
                row = session.scalar(select(AlertRuleRecord).where(
                    AlertRuleRecord.project_id == project_id,
                    AlertRuleRecord.rule_id == rule_id
                ).with_for_update())
                if row is None:
                    raise KeyError(rule_id)
                if expected_revision is not None and expected_revision != row.rule_version:
                    raise RuleConflict()
                audit = self._audit("delete", rule_id, row.rule_version, actor,
                                    projectId=project_id, requestId=request_id, before=row.payload, after=None)
                session.add(AlertRuleAuditRecord(
                    project_id=project_id,
                    rule_id=rule_id, action="delete", rule_version=row.rule_version,
                    actor=actor, payload=audit,
                ))
                audit_change(session, context, request_id, "rule.delete", "rule", rule_id, row.payload, None)
                session.execute(delete(AlertRuleBindingRecord).where(
                    AlertRuleBindingRecord.project_id == project_id,
                    AlertRuleBindingRecord.rule_id == rule_id,
                ))
                session.delete(row)
                return
        with self._lock:
            key = (project_id, rule_id)
            old = self._rules.get(key)
            if old is None: raise KeyError(rule_id)
            if expected_revision is not None and expected_revision != int(old["ruleVersion"]):
                raise RuleConflict()
            self._rules.pop(key)
            self._bindings.pop(key, None)
            self._audits.append(self._audit("delete", rule_id, int(old.get("ruleVersion", 1)), actor,
                                           projectId=project_id, requestId=request_id, before=old, after=None))
            audit_change(None, context, request_id, "rule.delete", "rule", rule_id, old, None)

    @serialized
    def bind(self, rule_id: str, source_id: str, capabilities: set[str] | list[str] | tuple[str, ...], *, model_id: str | None = None, actor: str = "admin", project_id: str = DEFAULT_PROJECT_ID,
             expected_revision: int | None = None, context=None, request_id: str | None = None) -> dict[str, Any]:
        if self._database is not None:
            with self._database.session() as session:
                lock_project(session, project_id)
                row = session.scalar(select(AlertRuleRecord).where(
                    AlertRuleRecord.project_id == project_id,
                    AlertRuleRecord.rule_id == rule_id
                ).with_for_update())
                if row is None:
                    raise KeyError(rule_id)
                if expected_revision is not None and expected_revision != row.rule_version:
                    raise RuleConflict()
                provided = set(capabilities)
                unknown = provided - set(CAPABILITIES)
                if unknown:
                    raise RuleValidationError(f"unknown capability: {sorted(unknown)}")
                result = self._check_rule(dict(row.payload), source_id, provided, model_id)
                row.rule_version += 1
                row.payload = {**row.payload, "ruleVersion": row.rule_version}
                result["ruleVersion"] = row.rule_version
                result["projectId"] = project_id
                binding = session.get(AlertRuleBindingRecord, (project_id, rule_id, source_id))
                before = copy.deepcopy(binding.payload) if binding else None
                if binding is None:
                    binding = AlertRuleBindingRecord(project_id=project_id, rule_id=rule_id, source_id=source_id, accepted=False, payload={})
                    session.add(binding)
                binding.accepted = bool(result.get("accepted"))
                binding.payload = copy.deepcopy(result)
                action = "bind" if binding.accepted else "reject"
                audit = self._audit(action, rule_id, row.rule_version, actor, sourceId=source_id,
                                    projectId=project_id, requestId=request_id, before=before, after=result,
                                    modelId=model_id, capabilities=sorted(provided),
                                    code=result.get("code"), missing=result.get("missing", []))
                session.add(AlertRuleAuditRecord(
                    project_id=project_id,
                    rule_id=rule_id, action=action, rule_version=row.rule_version,
                    actor=actor, payload=audit,
                ))
                audit_change(session, context, request_id, "rule." + action, "rule_binding", rule_id + "/" + source_id, before, result)
                return copy.deepcopy(result)
        with self._lock:
            key = (project_id, rule_id)
            if key not in self._rules: raise KeyError(rule_id)
            provided = set(capabilities); unknown = provided - set(CAPABILITIES)
            if unknown: raise RuleValidationError(f"unknown capability: {sorted(unknown)}")
            rule = self._rules[key]
            if expected_revision is not None and expected_revision != int(rule["ruleVersion"]):
                raise RuleConflict()
            result = self.check(rule_id, source_id, provided, model_id=model_id, project_id=project_id)
            rule["ruleVersion"] += 1
            result["ruleVersion"] = rule["ruleVersion"]
            result["projectId"] = project_id
            before = copy.deepcopy(self._bindings.get(key, {}).get(source_id))
            if not result.get("accepted", False):
                # Keep the refusal visible to administrators; it is deliberately
                # not treated as an active binding and is replaced by a later
                # successful bind for the same source.
                self._bindings.setdefault(key, {})[source_id] = copy.deepcopy(result)
                self._audits.append(self._audit("reject", rule_id, rule["ruleVersion"], actor, projectId=project_id, requestId=request_id, sourceId=source_id, modelId=model_id, before=before, after=copy.deepcopy(result), capabilities=sorted(provided), code=result.get("code"), missing=result.get("missing", [])))
                audit_change(None, context, request_id, "rule.reject", "rule_binding", rule_id + "/" + source_id, before, result)
                return result
            binding = {**result, "projectId": project_id}
            self._bindings.setdefault(key, {})[source_id] = binding
            self._audits.append(self._audit("bind", rule_id, rule["ruleVersion"], actor, projectId=project_id, requestId=request_id, sourceId=source_id, modelId=model_id, before=before, after=copy.deepcopy(binding), capabilities=sorted(provided)))
            audit_change(None, context, request_id, "rule.bind", "rule_binding", rule_id + "/" + source_id, before, binding)
            return copy.deepcopy(binding)

    @serialized
    def unbind(self, rule_id: str, source_id: str, *, expected_revision: int, actor: str,
               project_id: str, context=None, request_id=None) -> dict[str, Any]:
        if self._database is not None:
            with self._database.session() as session:
                lock_project(session, project_id)
                row = session.get(AlertRuleRecord, (project_id, rule_id))
                binding = session.get(AlertRuleBindingRecord, (project_id, rule_id, source_id))
                if row is None or binding is None:
                    raise KeyError(rule_id)
                if row.rule_version != expected_revision:
                    raise RuleConflict()
                before = copy.deepcopy(binding.payload)
                row.rule_version += 1
                row.payload = {**row.payload, "ruleVersion": row.rule_version}
                session.delete(binding)
                after = {"projectId": project_id, "ruleId": rule_id, "sourceId": source_id,
                         "ruleVersion": row.rule_version, "removed": True}
                audit = self._audit("unbind", rule_id, row.rule_version, actor, projectId=project_id,
                                    requestId=request_id, before=before, after=after)
                session.add(AlertRuleAuditRecord(project_id=project_id, rule_id=rule_id, action="unbind",
                                                rule_version=row.rule_version, actor=actor, payload=audit))
                audit_change(session, context, request_id, "rule.unbind", "rule_binding",
                             rule_id + "/" + source_id, before, after)
                return after
        key = (project_id, rule_id)
        rule = self._rules.get(key)
        before = self._bindings.get(key, {}).get(source_id)
        if rule is None or before is None:
            raise KeyError(rule_id)
        if rule["ruleVersion"] != expected_revision:
            raise RuleConflict()
        self._bindings[key].pop(source_id)
        rule["ruleVersion"] += 1
        after = {"projectId": project_id, "ruleId": rule_id, "sourceId": source_id,
                 "ruleVersion": rule["ruleVersion"], "removed": True}
        self._audits.append(self._audit("unbind", rule_id, rule["ruleVersion"], actor, projectId=project_id,
                                       requestId=request_id, before=before, after=after))
        audit_change(None, context, request_id, "rule.unbind", "rule_binding", rule_id + "/" + source_id, before, after)
        return after

    def check(self, rule_id: str, source_id: str, capabilities: set[str] | list[str] | tuple[str, ...], *, model_id: str | None = None, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        if self._database is not None:
            with self._database.session() as session:
                row = session.get(AlertRuleRecord, (project_id, rule_id))
                if row is None:
                    raise KeyError(rule_id)
                provided = set(capabilities)
                unknown = provided - set(CAPABILITIES)
                if unknown:
                    raise RuleValidationError(f"unknown capability: {sorted(unknown)}")
                return self._check_rule(dict(row.payload), source_id, provided, model_id)
        with self._lock:
            key = (project_id, rule_id)
            if key not in self._rules: raise KeyError(rule_id)
            provided = set(capabilities); unknown = provided - set(CAPABILITIES)
            if unknown: raise RuleValidationError(f"unknown capability: {sorted(unknown)}")
            rule = self._rules[key]; missing = sorted(set(rule.get("requires", ())) - provided)
            if missing:
                return {"accepted": False, "code": "CAPABILITY_UNSATISFIED", "message": f"缺少能力: {', '.join(missing)}", "ruleId": rule_id, "sourceId": source_id, "missing": missing, "modelId": model_id}
            if rule["operator"] in {"RELATION", "METRIC_THRESHOLD", "COMPOSITE"}:
                return {"accepted": False, "code": "OPERATOR_NOT_IMPLEMENTED", "message": f"operator {rule['operator']} is not implemented", "ruleId": rule_id, "sourceId": source_id}
            return {"accepted": True, "ruleId": rule_id, "sourceId": source_id, "modelId": model_id, "capabilities": sorted(provided), "ruleVersion": rule["ruleVersion"]}

    @staticmethod
    def _check_rule(rule: Mapping[str, Any], source_id: str, provided: set[str], model_id: str | None) -> dict[str, Any]:
        rule_id = str(rule["ruleId"])
        missing = sorted(set(rule.get("requires", ())) - provided)
        if missing:
            return {"accepted": False, "code": "CAPABILITY_UNSATISFIED", "message": f"缺少能力: {', '.join(missing)}", "ruleId": rule_id, "sourceId": source_id, "missing": missing, "modelId": model_id}
        if rule["operator"] in {"RELATION", "METRIC_THRESHOLD", "COMPOSITE"}:
            return {"accepted": False, "code": "OPERATOR_NOT_IMPLEMENTED", "message": f"operator {rule['operator']} is not implemented", "ruleId": rule_id, "sourceId": source_id}
        return {"accepted": True, "ruleId": rule_id, "sourceId": source_id, "modelId": model_id, "capabilities": sorted(provided), "ruleVersion": rule["ruleVersion"]}

    def bindings(self, rule_id: str, project_id: str = DEFAULT_PROJECT_ID) -> list[dict[str, Any]]:
        if self._database is not None:
            with self._database.session() as session:
                if session.get(AlertRuleRecord, (project_id, rule_id)) is None:
                    raise KeyError(rule_id)
                rows = session.scalars(select(AlertRuleBindingRecord).where(
                    AlertRuleBindingRecord.project_id == project_id,
                    AlertRuleBindingRecord.rule_id == rule_id
                ).order_by(AlertRuleBindingRecord.source_id)).all()
                return [copy.deepcopy(dict(row.payload)) for row in rows]
        with self._lock:
            key = (project_id, rule_id)
            if key not in self._rules: raise KeyError(rule_id)
            return [copy.deepcopy(v) for v in self._bindings.get(key, {}).values()]

    def audits(self, rule_id: str | None = None, project_id: str = DEFAULT_PROJECT_ID) -> list[dict[str, Any]]:
        if self._database is not None:
            with self._database.session() as session:
                query = select(AlertRuleAuditRecord).where(AlertRuleAuditRecord.project_id == project_id)
                if rule_id is not None:
                    query = query.where(AlertRuleAuditRecord.rule_id == rule_id)
                rows = session.scalars(query.order_by(AlertRuleAuditRecord.id)).all()
                return [copy.deepcopy(dict(row.payload)) for row in rows]
        with self._lock:
            rows = [x for x in self._audits if x.get("projectId") == project_id and (rule_id is None or x["ruleId"] == rule_id)]
            return copy.deepcopy(rows)


rule_registry = RuleRegistry(database if database.enabled else None)
