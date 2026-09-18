from __future__ import annotations

import json
import hashlib
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .conversion import atomic_json
from .database import (
    DatabaseManager,
    ModelParameterAuditRecord,
    ModelParameterProfileRecord,
    database,
)


PLATFORMS = {"android", "server"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
EVENT_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
PROFILE_SCHEMA_VERSION = 2

_DISPLAY_NAMES = {
    "head": "未佩戴安全帽",
    "helmet": "安全帽",
    "person": "人员",
    "no_helmet": "未佩戴安全帽",
    "no_goggle": "未佩戴护目镜",
    "no_gloves": "未佩戴手套",
    "no_boots": "未穿安全鞋",
}

_EVENT_CODES = {
    "head": "PPE_NO_HELMET",
    "no_helmet": "PPE_NO_HELMET",
    "no_goggle": "PPE_NO_GOGGLE",
    "no_gloves": "PPE_NO_GLOVES",
    "no_boots": "PPE_NO_BOOTS",
}


class ModelParameterError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ModelParameterConflict(ModelParameterError):
    pass


class ModelParameterStore:
    """Versioned parameter profiles kept outside signed model manifests."""

    def __init__(self, path: Path | None = None, database_manager: DatabaseManager | None = None):
        self.path = path or Path(__file__).resolve().parents[1] / "models" / "parameter-profiles.json"
        self._lock = threading.RLock()
        self._database = database_manager
        self._legacy_import_checked = False

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _profile_key(model: dict[str, Any], platform: str) -> str:
        return f"{model['modelId']}\0{model['version']}\0{platform}"

    @staticmethod
    def _database_profile_key(model_id: str, model_version: str, platform: str) -> str:
        identity = json.dumps([model_id, model_version, platform], ensure_ascii=False, separators=(",", ":"))
        return "mp-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @classmethod
    def _database_key_for_model(cls, model: dict[str, Any], platform: str) -> str:
        return cls._database_profile_key(str(model["modelId"]), str(model["version"]), platform)

    @staticmethod
    def _event_code(label: str) -> str:
        known = _EVENT_CODES.get(label.lower())
        if known:
            return known
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").upper()
        return ("DETECTION_" + normalized)[:64] if normalized else "DETECTION_OBJECT"

    def default_profile(self, model: dict[str, Any], platform: str) -> dict[str, Any]:
        self._validate_platform(platform)
        labels = list(model.get("labels") or [])
        rules = []
        for label in labels:
            normalized = label.lower()
            rules.append(
                {
                    "rawLabel": label,
                    "displayName": _DISPLAY_NAMES.get(normalized, label),
                    "eventCode": self._event_code(label),
                    "operator": "PRESENCE",
                    "enabled": normalized == "head",
                    "severity": "MAJOR",
                    "image": {
                        "minimumConfidence": 0.55,
                        "cooldownMs": 60000,
                    },
                    "camera": {
                        "minimumConfidence": 0.55,
                        "minimumConsecutiveFrames": 4,
                        "minimumDwellTimeMs": 800,
                        "cooldownMs": 60000,
                    },
                }
            )
        return {
            "schemaVersion": PROFILE_SCHEMA_VERSION,
            "modelId": model["modelId"],
            "modelName": model.get("name") or model["modelId"],
            "modelVersion": model["version"],
            "platform": platform,
            "revision": 0,
            "source": "default",
            "updatedAt": None,
            "updatedBy": None,
            "detection": {
                "confidenceThreshold": 0.35,
                "iouThreshold": 0.45,
                "maxDetections": 100,
            },
            "alertRules": rules,
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schemaVersion": PROFILE_SCHEMA_VERSION, "profiles": {}, "audit": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelParameterError("profile_store_unavailable", "model parameter store is unavailable") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), dict) or not isinstance(payload.get("audit"), list):
            raise ModelParameterError("profile_store_invalid", "model parameter store has an invalid structure")
        return payload

    def _import_legacy_once(self) -> None:
        if self._database is None or self._legacy_import_checked:
            return
        with self._lock:
            if self._legacy_import_checked:
                return
            payload = self._load()
            with self._database.session() as session:
                has_profiles = session.scalar(select(ModelParameterProfileRecord.profile_key).limit(1)) is not None
                if not has_profiles:
                    imported_keys: dict[str, str] = {}
                    for legacy_key, raw_profile in payload.get("profiles", {}).items():
                        if not isinstance(raw_profile, dict):
                            continue
                        profile = deepcopy(raw_profile)
                        model_id = str(profile.get("modelId") or "")
                        model_version = str(profile.get("modelVersion") or "")
                        platform = str(profile.get("platform") or "")
                        if not model_id or not model_version or platform not in PLATFORMS:
                            continue
                        key = self._database_profile_key(model_id, model_version, platform)
                        session.add(ModelParameterProfileRecord(
                            profile_key=key, model_id=model_id, model_version=model_version,
                            platform=platform, revision=int(profile.get("revision", 0)), payload=profile,
                        ))
                        imported_keys[str(legacy_key)] = key
                    session.flush()
                    for audit in payload.get("audit", []):
                        legacy_key = str(audit.get("profileKey") or "") if isinstance(audit, dict) else ""
                        key = imported_keys.get(legacy_key)
                        if key is None:
                            continue
                        audit_payload = deepcopy(audit)
                        audit_payload["profileKey"] = key
                        session.add(ModelParameterAuditRecord(
                            profile_key=key, action=str(audit.get("action") or "IMPORTED")[:32],
                            revision=int(audit.get("revision", 0)), actor=str(audit.get("actor") or "legacy-import")[:128],
                            payload=audit_payload,
                        ))
            self._legacy_import_checked = True

    def _database_payload(self, session, key: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        row = session.get(ModelParameterProfileRecord, key)
        audits = session.scalars(select(ModelParameterAuditRecord).where(
            ModelParameterAuditRecord.profile_key == key
        ).order_by(ModelParameterAuditRecord.id)).all()
        payload = {"schemaVersion": PROFILE_SCHEMA_VERSION, "profiles": {},
                   "audit": [deepcopy(dict(item.payload)) for item in audits]}
        if row is not None:
            payload["profiles"][key] = deepcopy(dict(row.payload))
        return payload, deepcopy(dict(row.payload)) if row is not None else None

    @staticmethod
    def _validate_platform(platform: str) -> None:
        if platform not in PLATFORMS:
            raise ModelParameterError("platform_invalid", "platform must be android or server")

    @staticmethod
    def _number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @classmethod
    def _normalize_profile(cls, model: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(profile, dict):
            raise ModelParameterError("profile_schema_invalid", "model parameter profile must be an object")
        version = profile.get("schemaVersion", 1)
        if version == 1:
            migrated = deepcopy(profile)
            migrated["schemaVersion"] = PROFILE_SCHEMA_VERSION
            migrated_rules = []
            for rule in migrated.get("alertRules", []):
                if not isinstance(rule, dict):
                    migrated_rules.append(rule)
                    continue
                legacy_confidence = rule.get("minimumConfidence")
                legacy_cooldown = rule.get("cooldownMs")
                migrated_rule = {
                    key: deepcopy(value)
                    for key, value in rule.items()
                    if key not in {"minimumConfidence", "minimumConsecutiveFrames", "minimumDwellTimeMs", "cooldownMs"}
                }
                migrated_rule["image"] = {
                    "minimumConfidence": legacy_confidence,
                    "cooldownMs": legacy_cooldown,
                }
                migrated_rule["camera"] = {
                    "minimumConfidence": legacy_confidence,
                    "minimumConsecutiveFrames": rule.get("minimumConsecutiveFrames"),
                    "minimumDwellTimeMs": rule.get("minimumDwellTimeMs"),
                    "cooldownMs": legacy_cooldown,
                }
                migrated_rules.append(migrated_rule)
            migrated["alertRules"] = migrated_rules
            return migrated
        if version != PROFILE_SCHEMA_VERSION:
            raise ModelParameterError("profile_schema_invalid", f"unsupported model parameter schema version: {version}")
        normalized = deepcopy(profile)
        normalized["schemaVersion"] = PROFILE_SCHEMA_VERSION
        normalized_rules = []
        for rule in normalized.get("alertRules", []):
            if isinstance(rule, dict):
                normalized_rules.append({
                    key: value
                    for key, value in rule.items()
                    if key not in {"minimumConfidence", "minimumConsecutiveFrames", "minimumDwellTimeMs", "cooldownMs"}
                })
            else:
                normalized_rules.append(rule)
        normalized["alertRules"] = normalized_rules
        return normalized

    @classmethod
    def _normalize_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise ModelParameterError("profile_schema_invalid", "model parameter values must be an object")
        requested_version = values.get("schemaVersion")
        if requested_version is None:
            requested_version = 2 if any(
                isinstance(rule, dict) and ("image" in rule or "camera" in rule)
                for rule in values.get("alertRules", [])
            ) else 1
        normalized = cls._normalize_profile({}, {**values, "schemaVersion": requested_version})
        return {"detection": normalized.get("detection"), "alertRules": normalized.get("alertRules")}

    @staticmethod
    def _validate_profile(model: dict[str, Any], profile: dict[str, Any]) -> None:
        detection = profile.get("detection") or {}
        confidence = detection.get("confidenceThreshold")
        iou = detection.get("iouThreshold")
        maximum = detection.get("maxDetections")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0.01 <= confidence <= 0.99:
            raise ModelParameterError("confidence_invalid", "confidenceThreshold must be between 0.01 and 0.99")
        if not isinstance(iou, (int, float)) or isinstance(iou, bool) or not 0.10 <= iou <= 0.90:
            raise ModelParameterError("iou_invalid", "iouThreshold must be between 0.10 and 0.90")
        if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 300:
            raise ModelParameterError("max_detections_invalid", "maxDetections must be between 1 and 300")

        labels = list(model.get("labels") or [])
        rules = profile.get("alertRules")
        if not isinstance(rules, list):
            raise ModelParameterError("alert_rules_invalid", "alertRules must be an array")
        raw_labels = [rule.get("rawLabel") for rule in rules if isinstance(rule, dict)]
        if len(raw_labels) != len(rules) or len(set(raw_labels)) != len(raw_labels):
            raise ModelParameterError("alert_label_duplicate", "alertRules cannot contain duplicate labels")
        if set(raw_labels) != set(labels) or len(raw_labels) != len(labels):
            raise ModelParameterError("alert_label_mismatch", "alertRules must cover every model label exactly once")
        for rule in rules:
            label = rule["rawLabel"]
            if not isinstance(rule.get("displayName"), str) or not rule["displayName"].strip() or len(rule["displayName"]) > 80:
                raise ModelParameterError("display_name_invalid", f"displayName is invalid for label {label}")
            event_code = rule.get("eventCode")
            if not isinstance(event_code, str) or not EVENT_CODE_PATTERN.fullmatch(event_code):
                raise ModelParameterError("event_code_invalid", f"eventCode is invalid for label {label}")
            if rule.get("operator") != "PRESENCE":
                raise ModelParameterError("operator_invalid", "model alert templates currently support PRESENCE only")
            image = rule.get("image")
            camera = rule.get("camera")
            if not isinstance(image, dict):
                raise ModelParameterError("image_alert_invalid", f"image parameters are required for label {label}")
            if not isinstance(camera, dict):
                raise ModelParameterError("camera_alert_invalid", f"camera parameters are required for label {label}")
            image_minimum = image.get("minimumConfidence")
            image_cooldown = image.get("cooldownMs")
            camera_minimum = camera.get("minimumConfidence")
            frames = camera.get("minimumConsecutiveFrames")
            dwell = camera.get("minimumDwellTimeMs")
            camera_cooldown = camera.get("cooldownMs")
            for field, value in (("image minimumConfidence", image_minimum), ("camera minimumConfidence", camera_minimum)):
                if not ModelParameterStore._number(value) or not 0.01 <= value <= 0.99:
                    raise ModelParameterError("alert_confidence_invalid", f"{field} is invalid for label {label}")
            if rule.get("enabled") and (image_minimum < confidence or camera_minimum < confidence):
                raise ModelParameterError("alert_confidence_too_low", f"alert confidence for {label} cannot be lower than detection confidence")
            if not isinstance(frames, int) or isinstance(frames, bool) or not 1 <= frames <= 120:
                raise ModelParameterError("frames_invalid", f"minimumConsecutiveFrames is invalid for label {label}")
            if not isinstance(dwell, int) or isinstance(dwell, bool) or not 0 <= dwell <= 600000:
                raise ModelParameterError("dwell_invalid", f"minimumDwellTimeMs is invalid for label {label}")
            if not isinstance(image_cooldown, int) or isinstance(image_cooldown, bool) or not 0 <= image_cooldown <= 86400000:
                raise ModelParameterError("image_cooldown_invalid", f"image cooldownMs is invalid for label {label}")
            if not isinstance(camera_cooldown, int) or isinstance(camera_cooldown, bool) or not 0 <= camera_cooldown <= 86400000:
                raise ModelParameterError("cooldown_invalid", f"camera cooldownMs is invalid for label {label}")
            if rule.get("severity") not in SEVERITIES:
                raise ModelParameterError("severity_invalid", f"severity is invalid for label {label}")

    def _response(self, payload: dict[str, Any], profile: dict[str, Any], key: str) -> dict[str, Any]:
        result = deepcopy(profile)
        result["schemaVersion"] = PROFILE_SCHEMA_VERSION
        for rule in result.get("alertRules", []):
            camera = rule.get("camera") or {}
            # Keep the v1 projection until all mobile clients consume scene-specific fields.
            rule["minimumConfidence"] = camera.get("minimumConfidence")
            rule["minimumConsecutiveFrames"] = camera.get("minimumConsecutiveFrames")
            rule["minimumDwellTimeMs"] = camera.get("minimumDwellTimeMs")
            rule["cooldownMs"] = camera.get("cooldownMs")
        result["audit"] = [
            {field: item.get(field) for field in ("action", "revision", "at", "actor")}
            for item in payload["audit"]
            if item.get("profileKey") == key
        ][-20:]
        return result

    def get(self, model: dict[str, Any], platform: str) -> dict[str, Any]:
        self._validate_platform(platform)
        if self._database is not None:
            self._import_legacy_once()
            key = self._database_key_for_model(model, platform)
            with self._database.session() as session:
                payload, stored = self._database_payload(session, key)
                profile = self.default_profile(model, platform) if stored is None else self._normalize_profile(model, stored)
                self._validate_profile(model, profile)
                return self._response(payload, profile, key)
        with self._lock:
            payload = self._load()
            payload["schemaVersion"] = PROFILE_SCHEMA_VERSION
            key = self._profile_key(model, platform)
            stored = payload["profiles"].get(key)
            profile = self.default_profile(model, platform) if stored is None else self._normalize_profile(model, stored)
            self._validate_profile(model, profile)
            return self._response(payload, profile, key)

    def save(
        self,
        model: dict[str, Any],
        platform: str,
        values: dict[str, Any],
        actor: str,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        self._validate_platform(platform)
        values = self._normalize_values(values)
        candidate = {
            "schemaVersion": PROFILE_SCHEMA_VERSION,
            "modelId": model["modelId"],
            "modelName": model.get("name") or model["modelId"],
            "modelVersion": model["version"],
            "platform": platform,
            "revision": 0,
            "source": "custom",
            "updatedAt": None,
            "updatedBy": None,
            "detection": deepcopy(values.get("detection")),
            "alertRules": deepcopy(values.get("alertRules")),
        }
        self._validate_profile(model, candidate)
        if self._database is not None:
            self._import_legacy_once()
            key = self._database_key_for_model(model, platform)
            with self._database.session() as session:
                row = session.scalar(select(ModelParameterProfileRecord).where(
                    ModelParameterProfileRecord.profile_key == key
                ).with_for_update())
                current_profile = self._normalize_profile(model, row.payload) if row else None
                revision = int(current_profile.get("revision", 0)) if current_profile else 0
                if expected_revision is not None and expected_revision != revision:
                    raise ModelParameterConflict("revision_conflict", "model parameters were changed by another operator")
                now = self._now()
                profile = {
                    "schemaVersion": PROFILE_SCHEMA_VERSION, "modelId": model["modelId"],
                    "modelName": model.get("name") or model["modelId"], "modelVersion": model["version"],
                    "platform": platform, "revision": revision + 1, "source": "custom",
                    "updatedAt": now, "updatedBy": actor, "detection": deepcopy(values["detection"]),
                    "alertRules": deepcopy(values["alertRules"]),
                }
                if row is None:
                    row = ModelParameterProfileRecord(
                        profile_key=key, model_id=model["modelId"], model_version=model["version"],
                        platform=platform, revision=profile["revision"], payload=profile,
                    )
                    session.add(row)
                else:
                    row.revision = profile["revision"]
                    row.payload = deepcopy(profile)
                session.flush()
                audit = {"profileKey": key, "action": "UPDATED", "revision": profile["revision"],
                         "at": now, "actor": actor, "snapshot": deepcopy(profile)}
                session.add(ModelParameterAuditRecord(
                    profile_key=key, action="UPDATED", revision=profile["revision"], actor=actor, payload=audit,
                ))
                session.flush()
                payload, _ = self._database_payload(session, key)
                return self._response(payload, profile, key)
        with self._lock:
            payload = self._load()
            payload["schemaVersion"] = PROFILE_SCHEMA_VERSION
            key = self._profile_key(model, platform)
            current = payload["profiles"].get(key)
            current_profile = self._normalize_profile(model, current) if current else None
            revision = int(current_profile.get("revision", 0)) if current_profile else 0
            if expected_revision is not None and expected_revision != revision:
                raise ModelParameterConflict("revision_conflict", "model parameters were changed by another operator")
            now = self._now()
            profile = {
                "schemaVersion": PROFILE_SCHEMA_VERSION,
                "modelId": model["modelId"],
                "modelName": model.get("name") or model["modelId"],
                "modelVersion": model["version"],
                "platform": platform,
                "revision": revision + 1,
                "source": "custom",
                "updatedAt": now,
                "updatedBy": actor,
                "detection": deepcopy(values["detection"]),
                "alertRules": deepcopy(values["alertRules"]),
            }
            payload["profiles"][key] = profile
            payload["audit"].append(
                {"profileKey": key, "action": "UPDATED", "revision": profile["revision"], "at": now, "actor": actor, "snapshot": deepcopy(profile)}
            )
            payload["audit"] = payload["audit"][-500:]
            atomic_json(self.path, payload)
            return self._response(payload, profile, key)

    def reset(self, model: dict[str, Any], platform: str, actor: str) -> dict[str, Any]:
        self._validate_platform(platform)
        if self._database is not None:
            self._import_legacy_once()
            key = self._database_key_for_model(model, platform)
            with self._database.session() as session:
                row = session.scalar(select(ModelParameterProfileRecord).where(
                    ModelParameterProfileRecord.profile_key == key
                ).with_for_update())
                current_profile = self._normalize_profile(model, row.payload) if row else None
                revision = int(current_profile.get("revision", 0)) if current_profile else 0
                now = self._now()
                profile = self.default_profile(model, platform)
                profile.update({"revision": revision + 1, "updatedAt": now, "updatedBy": actor})
                if row is None:
                    row = ModelParameterProfileRecord(
                        profile_key=key, model_id=model["modelId"], model_version=model["version"],
                        platform=platform, revision=profile["revision"], payload=profile,
                    )
                    session.add(row)
                else:
                    row.revision = profile["revision"]
                    row.payload = deepcopy(profile)
                session.flush()
                audit = {"profileKey": key, "action": "RESET", "revision": profile["revision"],
                         "at": now, "actor": actor, "snapshot": deepcopy(profile)}
                session.add(ModelParameterAuditRecord(
                    profile_key=key, action="RESET", revision=profile["revision"], actor=actor, payload=audit,
                ))
                session.flush()
                payload, _ = self._database_payload(session, key)
                return self._response(payload, profile, key)
        with self._lock:
            payload = self._load()
            payload["schemaVersion"] = PROFILE_SCHEMA_VERSION
            key = self._profile_key(model, platform)
            current = payload["profiles"].get(key)
            current_profile = self._normalize_profile(model, current) if current else None
            revision = int(current_profile.get("revision", 0)) if current_profile else 0
            now = self._now()
            profile = self.default_profile(model, platform)
            profile.update({"revision": revision + 1, "updatedAt": now, "updatedBy": actor})
            payload["profiles"][key] = profile
            payload["audit"].append(
                {"profileKey": key, "action": "RESET", "revision": profile["revision"], "at": now, "actor": actor, "snapshot": deepcopy(profile)}
            )
            payload["audit"] = payload["audit"][-500:]
            atomic_json(self.path, payload)
            return self._response(payload, profile, key)
