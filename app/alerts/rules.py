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

from .geometry import Roi, RoiGeometryError
from .observation import CAPABILITIES

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


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, dict[str, Any]] = {}
        self._bindings: dict[str, dict[str, dict[str, Any]]] = {}
        self._audits: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    @staticmethod
    def _normalise(rule: Mapping[str, Any], existing: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = copy.deepcopy(dict(existing or {})); data.update(copy.deepcopy(dict(rule)))
        rid = str(data.get("ruleId", ""))
        if not RULE_ID.fullmatch(rid): raise RuleValidationError("ruleId must match [A-Za-z0-9_.-]{1,64}")
        op = str(data.get("operator", "")).upper()
        if op not in OPS: raise RuleValidationError(f"unsupported operator: {op}")
        subject = str(data.get("subjectKind", "track"))
        if subject not in {"track", "frame", "roi", "metric", "source"}: raise RuleValidationError("invalid subjectKind")
        requires = set(data.get("requires") or OPERATOR_REQUIREMENTS.get(op, set()))
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
                "timestamp": datetime.now(timezone.utc).isoformat(), **extra}

    def list(self) -> list[dict[str, Any]]:
        with self._lock: return [copy.deepcopy(v) for v in self._rules.values()]

    def get(self, rule_id: str) -> dict[str, Any]:
        with self._lock:
            if rule_id not in self._rules: raise KeyError(rule_id)
            result = copy.deepcopy(self._rules[rule_id]); result["bindings"] = copy.deepcopy(self._bindings.get(rule_id, {})); return result

    def upsert(self, rule: Mapping[str, Any], *, actor: str = "admin") -> dict[str, Any]:
        with self._lock:
            rid = str(rule.get("ruleId", "")); old = self._rules.get(rid)
            data = self._normalise(rule, old)
            if old: data["ruleVersion"] = int(old.get("ruleVersion", 1)) + 1
            self._rules[rid] = data
            self._audits.append(self._audit("update" if old else "create", rid, data["ruleVersion"], actor))
            return copy.deepcopy(data)

    def delete(self, rule_id: str, *, actor: str = "admin") -> None:
        with self._lock:
            old = self._rules.pop(rule_id, None)
            if old is None: raise KeyError(rule_id)
            self._bindings.pop(rule_id, None)
            self._audits.append(self._audit("delete", rule_id, int(old.get("ruleVersion", 1)), actor))

    def bind(self, rule_id: str, source_id: str, capabilities: set[str] | list[str] | tuple[str, ...], *, model_id: str | None = None, actor: str = "admin") -> dict[str, Any]:
        with self._lock:
            if rule_id not in self._rules: raise KeyError(rule_id)
            provided = set(capabilities); unknown = provided - set(CAPABILITIES)
            if unknown: raise RuleValidationError(f"unknown capability: {sorted(unknown)}")
            rule = self._rules[rule_id]; required = set(rule.get("requires", ()))
            result = self.check(rule_id, source_id, provided, model_id=model_id)
            if not result.get("accepted", False):
                # Keep the refusal visible to administrators; it is deliberately
                # not treated as an active binding and is replaced by a later
                # successful bind for the same source.
                self._bindings.setdefault(rule_id, {})[source_id] = copy.deepcopy(result)
                self._audits.append(self._audit("reject", rule_id, rule["ruleVersion"], actor, sourceId=source_id, modelId=model_id, code=result.get("code"), missing=result.get("missing", [])))
                return result
            binding = {"accepted": True, "ruleId": rule_id, "sourceId": source_id, "modelId": model_id, "capabilities": sorted(provided), "ruleVersion": rule["ruleVersion"]}
            self._bindings.setdefault(rule_id, {})[source_id] = binding
            self._audits.append(self._audit("bind", rule_id, rule["ruleVersion"], actor, sourceId=source_id, modelId=model_id, capabilities=sorted(provided)))
            return copy.deepcopy(binding)

    def check(self, rule_id: str, source_id: str, capabilities: set[str] | list[str] | tuple[str, ...], *, model_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if rule_id not in self._rules: raise KeyError(rule_id)
            provided = set(capabilities); unknown = provided - set(CAPABILITIES)
            if unknown: raise RuleValidationError(f"unknown capability: {sorted(unknown)}")
            rule = self._rules[rule_id]; missing = sorted(set(rule.get("requires", ())) - provided)
            if missing:
                return {"accepted": False, "code": "CAPABILITY_UNSATISFIED", "message": f"缺少能力: {', '.join(missing)}", "ruleId": rule_id, "sourceId": source_id, "missing": missing, "modelId": model_id}
            if rule["operator"] in {"RELATION", "METRIC_THRESHOLD", "COMPOSITE"}:
                return {"accepted": False, "code": "OPERATOR_NOT_IMPLEMENTED", "message": f"operator {rule['operator']} is not implemented", "ruleId": rule_id, "sourceId": source_id}
            return {"accepted": True, "ruleId": rule_id, "sourceId": source_id, "modelId": model_id, "capabilities": sorted(provided), "ruleVersion": rule["ruleVersion"]}

    def bindings(self, rule_id: str) -> list[dict[str, Any]]:
        with self._lock:
            if rule_id not in self._rules: raise KeyError(rule_id)
            return [copy.deepcopy(v) for v in self._bindings.get(rule_id, {}).values()]

    def audits(self, rule_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._audits if rule_id is None else [x for x in self._audits if x["ruleId"] == rule_id]
            return copy.deepcopy(rows)


rule_registry = RuleRegistry()
