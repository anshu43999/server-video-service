from __future__ import annotations

import json
import hashlib
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from .conversion import atomic_json
from .database import (
    DatabaseManager,
    ModelParameterAuditRecord,
    ModelParameterProfileRecord,
    DEFAULT_PROJECT_ID,
)
from .project_business import audit_change, lock_project, serialized


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
                lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
                has_profiles = session.scalar(select(ModelParameterProfileRecord.profile_key).where(
                    ModelParameterProfileRecord.project_id == DEFAULT_PROJECT_ID,
                    ModelParameterProfileRecord.scope == "PLATFORM",
                ).limit(1)) is not None
                if not has_profiles:
                    imported_keys: dict[str, str] = {}
                    for legacy_key, raw_profile in payload.get("profiles", {}).items():
                        if not isinstance(raw_profile, dict):
                            continue
                        profile = deepcopy(raw_profile)
                        if str(legacy_key).startswith("[") or profile.get("projectId") not in {None, DEFAULT_PROJECT_ID}:
                            continue
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

    def _database_payload(self, session, key: str, project_id: str = DEFAULT_PROJECT_ID) -> tuple[dict[str, Any], dict[str, Any] | None]:
        row = session.get(ModelParameterProfileRecord, (project_id, key))
        audits = session.scalars(select(ModelParameterAuditRecord).where(
            ModelParameterAuditRecord.project_id == project_id,
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

    @staticmethod
    def _platform_only(project_id):
        if project_id is not None:
            raise ModelParameterError("platform_parameters_read_only", "model parameters are maintained by the platform")

    @staticmethod
    def _authority(session, context):
        if context is None:
            return  # Internal tools/tests; HTTP entry points always supply a principal.
        from .database import AccountRecord
        # Recheck current account under the same transaction as publication.
        principal = getattr(context, "principal", context)
        if session is not None:
            account = session.scalar(select(AccountRecord).where(
                AccountRecord.account_id == principal.account_id).with_for_update())
            if account is None or not account.enabled or account.platform_role != "PLATFORM_ADMIN":
                raise ModelParameterError("capability_required", "platform model authority was revoked")

    @staticmethod
    def _publication(payload, key):
        return next((deepcopy(item["snapshot"]) for item in reversed(payload["audit"])
                     if item.get("profileKey") == key and item.get("action") == "PUBLISHED"), None)

    @serialized
    def publication_status(self, models):
        """Batch platform-only catalog hints, without exposing editable profiles."""
        if not models:
            return {}
        if self._database is not None:
            self._import_legacy_once()
            keys = [self._database_key_for_model(model, platform)
                    for model in models for platform in sorted(PLATFORMS)]
            with self._database.session() as session:
                profiles = {row.profile_key: row.payload for row in session.scalars(
                    select(ModelParameterProfileRecord).where(
                        ModelParameterProfileRecord.project_id == DEFAULT_PROJECT_ID,
                        ModelParameterProfileRecord.scope == "PLATFORM",
                        ModelParameterProfileRecord.profile_key.in_(keys)))}
                latest = select(func.max(ModelParameterAuditRecord.id)).where(
                    ModelParameterAuditRecord.project_id == DEFAULT_PROJECT_ID,
                    ModelParameterAuditRecord.profile_key.in_(keys),
                    ModelParameterAuditRecord.action == "PUBLISHED",
                ).group_by(ModelParameterAuditRecord.profile_key)
                publications = {row.profile_key: row.payload.get("snapshot") for row in session.scalars(
                    select(ModelParameterAuditRecord).where(ModelParameterAuditRecord.id.in_(latest)))}
            key_for = self._database_key_for_model
        else:
            payload = self._load()
            profiles = payload["profiles"]
            publications = {item.get("profileKey"): item.get("snapshot") for item in payload["audit"]
                            if item.get("action") == "PUBLISHED"}
            key_for = self._profile_key
        results = {}
        for model in models:
            states = {}
            for platform in sorted(PLATFORMS):
                key = key_for(model, platform)
                published = publications.get(key)
                revision = published.get("revision") if isinstance(published, dict) else None
                state = "unpublished"
                if key in publications:
                    try:
                        if not isinstance(published, dict) or isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                            raise ModelParameterError("profile_invalid", "invalid publication")
                        self._validate_profile(model, published)
                        state = "published"
                    except ModelParameterError:
                        state, revision = "unavailable", None
                draft = profiles.get(key) or {}
                states[platform] = {
                    "state": state, "publishedRevision": revision,
                    "hasUnpublishedChanges": state == "unpublished" or
                    state == "published" and draft.get("revision", 0) != revision,
                }
            results[(model["modelId"], model["version"])] = states
        return results

    @serialized
    def get(self, model, platform, project_id=None):
        self._validate_platform(platform)
        if project_id is not None:
            return self.published(model, platform, project_id)
        if self._database is not None:
            self._import_legacy_once()
            key = self._database_key_for_model(model, platform)
            with self._database.session() as session:
                payload, stored = self._database_payload(session, key)
        else:
            payload = self._load()
            key = self._profile_key(model, platform)
            stored = payload["profiles"].get(key)
        profile = self._normalize_profile(model, stored) if stored else self.default_profile(model, platform)
        self._validate_profile(model, profile)
        result = self._response(payload, profile, key)
        published = self._publication(payload, key)
        result["publishedRevision"] = published["revision"] if published else None
        result["hasUnpublishedChanges"] = published is None or published["revision"] != profile["revision"]
        return result

    @serialized
    def published(self, model, platform, project_id=None):
        self._validate_platform(platform)
        if self._database is not None:
            self._import_legacy_once()
            key = self._database_key_for_model(model, platform)
            with self._database.session() as session:
                payload, _ = self._database_payload(session, key)
        else:
            key = self._profile_key(model, platform)
            payload = self._load()
        profile = self._publication(payload, key)
        if profile is None:
            raise ModelParameterError("platform_parameters_unpublished", "platform parameters must be published before use")
        self._validate_profile(model, profile)
        if project_id is not None:
            profile["projectId"] = project_id
        return profile

    @serialized
    def save(self, model, platform, values, actor, expected_revision, project_id=None,
             context=None, request_id=None):
        self._platform_only(project_id)
        values = self._normalize_values(values)
        return self._write(model, platform, values, actor, expected_revision, "UPDATED",
                           context, request_id)

    @serialized
    def reset(self, model, platform, actor, project_id=None, expected_revision=None,
              context=None, request_id=None):
        self._platform_only(project_id)
        return self._write(model, platform, self.default_profile(model, platform), actor,
                           expected_revision, "RESET", context, request_id)

    @serialized
    def publish(self, model, platform, actor, expected_revision, expected_published_revision,
                context=None, request_id=None):
        return self._write(model, platform, None, actor, expected_revision, "PUBLISHED",
                           context, request_id, expected_published_revision=expected_published_revision)

    def _write(self, model, platform, values, actor, expected, action, context, request_id,
               expected_published_revision=None):
        from contextlib import nullcontext
        self._validate_platform(platform)
        if self._database is not None:
            self._import_legacy_once()
        with (self._database.session() if self._database is not None else nullcontext(None)) as session:
            if session is not None:
                lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
                self._authority(session, context)
                key = self._database_key_for_model(model, platform)
                payload, stored = self._database_payload(session, key)
            else:
                key = self._profile_key(model, platform)
                payload = self._load()
                stored = payload["profiles"].get(key)
            current = self._normalize_profile(model, stored) if stored else self.default_profile(model, platform)
            revision = current["revision"]
            if expected is not None and expected != revision:
                raise ModelParameterConflict("revision_conflict", "model parameter draft was changed")
            previous = self._publication(payload, key)
            if action == "PUBLISHED":
                previous_revision = previous["revision"] if previous else None
                if previous_revision != expected_published_revision:
                    raise ModelParameterConflict("publication_conflict", "published model parameters were changed")
                if previous_revision == revision:
                    return previous
                profile = {k: deepcopy(current[k]) for k in
                           ("schemaVersion", "modelId", "modelVersion", "platform", "revision",
                            "detection", "alertRules")}
                profile.update(source="platform", updatedAt=self._now())
                draft = current
            else:
                profile = {**self.default_profile(model, platform),
                           "detection": deepcopy(values["detection"]), "alertRules": deepcopy(values["alertRules"]),
                           "revision": revision + 1, "source": "default" if action == "RESET" else "custom",
                           "updatedAt": self._now(), "updatedBy": actor}
                draft = profile
            self._validate_profile(model, profile)
            audit = {"profileKey": key, "action": action, "revision": profile["revision"],
                     "at": self._now(), "actor": actor, "snapshot": deepcopy(profile)}
            if session is not None:
                row = session.get(ModelParameterProfileRecord, (DEFAULT_PROJECT_ID, key))
                if row is None:
                    row = ModelParameterProfileRecord(project_id=DEFAULT_PROJECT_ID, scope="PLATFORM",
                        profile_key=key, model_id=model["modelId"], model_version=model["version"],
                        platform=platform, revision=draft["revision"], payload=deepcopy(draft))
                    session.add(row)
                elif action != "PUBLISHED":
                    row.revision, row.payload = draft["revision"], deepcopy(draft)
                session.flush()
                session.add(ModelParameterAuditRecord(project_id=DEFAULT_PROJECT_ID, profile_key=key,
                    action=action, revision=profile["revision"], actor=actor, payload=audit))
            else:
                payload["profiles"][key] = deepcopy(draft)
                payload["audit"].append(audit)  # Published history must never be truncated.
                atomic_json(self.path, payload)
            audit_change(session, context, request_id, "model_parameters." + action.lower(),
                         "model_parameters", key, previous if action == "PUBLISHED" else current, profile)
        return self.published(model, platform) if action == "PUBLISHED" else self.get(model, platform)
