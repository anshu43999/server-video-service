"""Project scene configuration; does not schedule or mutate inference bindings."""
from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import secrets
from threading import RLock
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError

from .database import (DEFAULT_PROJECT_ID, ProjectRecord, ProjectMembershipRecord, AccountRecord,
                       ProjectSceneRecord, ProjectSceneMemberRecord, ProjectScenePlanRecord,
                       ProjectScenePlanMemberRecord, ProjectSceneInstallationRecord,
                       ProjectSceneRuntimeGrantRecord)
from .project_auth import (PROJECT_READ, PROJECT_SCENES_MANAGE, PROJECT_SCENES_APPROVE,
                           PROJECT_INSPECTION_USE, PROJECT_MODELS_ASSIGN, require_project_capability)
from .project_business import audit_change, lock_project
from .project_model_policy import project_target_usable
from .scene_parameter_digest import parameter_digest
from .model_display import model_display_name
from .resource_lifecycle import (deletion_headers, operation_identity, add_event, guard_model_write)
from .database import ResourceLifecycleOperationRecord

_scene_lock = RLock()


def reject(code, message, status=409):
    raise HTTPException(status, detail={"code": code, "message": message})


class SceneMember(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    memberId: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    projectModelId: str = Field(min_length=1, max_length=36)
    position: StrictInt = Field(ge=0)
    inputTypes: list[Literal["image", "video"]] | None = Field(default=None, min_length=1, max_length=2)
    execution: Literal["single", "sync", "async"] = "single"
    parameterRevision: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_member(self):
        if self.inputTypes is not None and len(set(self.inputTypes)) != len(self.inputTypes):
            raise ValueError("member inputTypes must be unique")
        return self


def _derived_member_id(project_model_id: str) -> str:
    digest = sha256(project_model_id.encode("utf-8")).hexdigest()[:24]
    return f"member-{digest}"


def ordered_members(members):
    if sorted(m.position for m in members) != list(range(len(members))):
        raise ValueError("member positions must be contiguous from zero")
    keys = [m.projectModelId for m in members]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate project model")
    result = []
    for member in sorted((m.model_dump() for m in members), key=lambda m: m["position"]):
        member["memberId"] = member.get("memberId") or _derived_member_id(member["projectModelId"])
        if member.get("inputTypes") is None:
            member.pop("inputTypes", None)
        result.append(member)
    if len({m["memberId"] for m in result}) != len(result):
        raise ValueError("duplicate memberId")
    return result


class CameraPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frameInterval: StrictInt = Field(default=5, ge=1, le=120)
    batchTimeoutMs: StrictInt = Field(default=5000, ge=1000, le=10000)
    resultMaxAgeMs: StrictInt = Field(default=6000, ge=1000, le=15000)
    overlayHoldMs: StrictInt = Field(default=1500, ge=0, le=3000)

    @model_validator(mode="after")
    def validate_age(self):
        if self.resultMaxAgeMs < self.batchTimeoutMs:
            raise ValueError("camera resultMaxAgeMs must be at least batchTimeoutMs")
        return self


class ScenePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    planId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=255)
    inputTypes: list[Literal["image", "video"]] = Field(min_length=1, max_length=2)
    memberIds: list[str] = Field(min_length=1, max_length=100)
    execution: Literal["single", "sync", "async"] = "single"
    enabled: bool = True
    cameraPolicy: CameraPolicy = Field(default_factory=CameraPolicy)

    @model_validator(mode="after")
    def validate_plan(self):
        if len(set(self.inputTypes)) != len(self.inputTypes):
            raise ValueError("plan inputTypes must be unique")
        if len(set(self.memberIds)) != len(self.memberIds):
            raise ValueError("plan memberIds must be unique")
        if self.execution == "single" and len(self.memberIds) != 1:
            raise ValueError("single plan must select exactly one member")
        return self


class SceneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sceneId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=255)
    inputTypes: list[Literal["image", "video"]] = Field(min_length=1, max_length=2)
    models: list[SceneMember] = Field(min_length=1, max_length=100)
    plans: list[ScenePlan] = Field(default_factory=list, max_length=100)
    enabled: bool = True
    expectedRevision: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_scene(self):
        if len(set(self.inputTypes)) != len(self.inputTypes):
            raise ValueError("inputTypes must be unique")
        ordered_members(self.models)
        member_ids = {member.memberId or _derived_member_id(member.projectModelId)
                      for member in self.models}
        if len({plan.planId for plan in self.plans}) != len(self.plans):
            raise ValueError("duplicate planId")
        if any(not set(plan.memberIds).issubset(member_ids) for plan in self.plans):
            raise ValueError("plan references an unknown memberId")
        return self


class ScenePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    inputTypes: list[Literal["image", "video"]] | None = Field(default=None, min_length=1, max_length=2)
    enabled: bool | None = None
    plans: list[ScenePlan] | None = Field(default=None, max_length=100)
    expectedRevision: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def validate_patch(self):
        fields = self.model_fields_set - {"expectedRevision"}
        if not fields or any(getattr(self, field) is None for field in fields):
            raise ValueError("patch requires at least one non-null configuration field")
        if self.inputTypes is not None and len(set(self.inputTypes)) != len(self.inputTypes):
            raise ValueError("inputTypes must be unique")
        return self


class SceneModels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: list[SceneMember] = Field(min_length=1, max_length=100)
    expectedRevision: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def validate_models(self):
        ordered_members(self.models)
        return self


class SceneApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    approved: bool
    expectedRevision: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=512)


class ScenePlans(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plans: list[ScenePlan] = Field(max_length=100)
    expectedRevision: StrictInt = Field(ge=1)


class SceneResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: StrictInt = Field(ge=1)
    target: Literal["pc", "mobile"]
    inputType: Literal["image", "video"]


class ScenePlanResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planId: str = Field(min_length=1, max_length=128)
    expectedRevision: StrictInt = Field(ge=1)
    target: Literal["pc", "mobile"]
    inputType: Literal["image", "video"]
    clientContractVersion: StrictInt = Field(default=2, ge=1, le=100)
    supportedExecutionModes: list[Literal["single", "sync", "async"]] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_capabilities(self):
        if len(set(self.supportedExecutionModes)) != len(self.supportedExecutionModes):
            raise ValueError("supportedExecutionModes must be unique")
        return self


class SceneRuntimeGrantRequest(ScenePlanResolution):
    grantToken: str | None = Field(default=None, min_length=32, max_length=256)
    operation: Literal["start", "renew", "heartbeat", "stop"] = "start"


class SceneRuntimeGrant:
    """Short-lived online lease; only token digests are persisted."""
    ttl = timedelta(minutes=2)

    def __init__(self, database):
        self.database = database
        self._lock = RLock()
        self._leases = {}
        self._stopped = {}
        self._requests = {}

    @staticmethod
    def _key(token):
        return sha256(token.encode("utf-8")).hexdigest()

    def issue(self, scope, *, session=None, request_digest=None):
        execution = scope.get("execution", "single")
        members = deepcopy(scope.get("members") or [{
            "memberId": scope["memberId"], "modelId": scope["modelId"],
            "modelVersion": scope["modelVersion"], "artifactId": scope["artifactId"],
            "artifactSha256": scope["artifactSha256"],
            "parameterRevision": scope["parameterRevision"],
        }])
        token = secrets.token_urlsafe(40)
        expires_at = datetime.now(timezone.utc) + self.ttl
        digest = self._key(token)
        if self.database is not None and self.database.enabled:
            row = ProjectSceneRuntimeGrantRecord(
                grant_id=secrets.token_hex(16), token_digest=digest,
                project_id=scope["projectId"], scene_id=scope["sceneId"],
                account_id=scope["accountId"], scene_revision=scope["expectedRevision"],
                plan_id=scope["planId"], member_id=scope["memberId"],
                input_type=scope["inputType"], target=scope["target"],
                client_contract_version=scope["clientContractVersion"],
                supported_execution_modes=list(scope["supportedExecutionModes"]),
                execution_mode=execution, member_snapshot=members,
                authority_snapshot=deepcopy(scope.get("authority", {})),
                request_digest=request_digest,
                model_id=scope["modelId"], model_version=scope["modelVersion"],
                artifact_id=scope["artifactId"], artifact_sha256=scope["artifactSha256"],
                parameter_revision=scope["parameterRevision"], expires_at=expires_at,
            )
            with (nullcontext(session) if session is not None else self.database.session()) as session:
                cutoff = datetime.now(timezone.utc) - timedelta(days=1)
                expired_ids = select(ProjectSceneRuntimeGrantRecord.grant_id).where(or_(
                    ProjectSceneRuntimeGrantRecord.expires_at < cutoff,
                    ProjectSceneRuntimeGrantRecord.revoked_at < cutoff,
                )).order_by(ProjectSceneRuntimeGrantRecord.expires_at).limit(500)
                session.execute(delete(ProjectSceneRuntimeGrantRecord).where(
                    ProjectSceneRuntimeGrantRecord.grant_id.in_(expired_ids)))
                session.add(row)
                session.flush()
        else:
            with self._lock:
                cutoff = datetime.now(timezone.utc)
                self._leases = {key: lease for key, lease in self._leases.items()
                                if lease["expiresAt"] > cutoff}
                self._requests = {key: expiry for key, expiry in self._requests.items()
                                  if expiry > cutoff - timedelta(days=1)}
                if request_digest and request_digest in self._requests:
                    reject("runtime_grant_request_replayed", "runtime grant request was already processed", 409)
                if request_digest:
                    self._requests[request_digest] = expires_at
                self._leases[digest] = {**deepcopy(scope), "execution": execution,
                                        "members": members, "expiresAt": expires_at}
        return token, expires_at

    def get(self, token, expected_scope=None, *, session=None, stopping=False):
        if not token:
            reject("runtime_grant_required", "runtime grant is required", 403)
        key = self._key(token)
        if self.database is not None and self.database.enabled:
            with (nullcontext(session) if session is not None else self.database.session()) as session:
                row = session.scalar(select(ProjectSceneRuntimeGrantRecord).where(
                    ProjectSceneRuntimeGrantRecord.token_digest == key).with_for_update())
                if row is None or (row.revoked_at is not None and not stopping):
                    reject("runtime_grant_invalid", "runtime grant is invalid or revoked", 403)
                expires_at = row.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                scope = {"accountId": row.account_id, "projectId": row.project_id,
                    "sceneId": row.scene_id, "expectedRevision": row.scene_revision,
                    "planId": row.plan_id, "memberId": row.member_id, "inputType": row.input_type,
                    "target": row.target, "clientContractVersion": row.client_contract_version,
                    "supportedExecutionModes": list(row.supported_execution_modes),
                    "execution": row.execution_mode or "single",
                    "authority": deepcopy(row.authority_snapshot or {}),
                    "members": deepcopy(row.member_snapshot or [{
                        "memberId": row.member_id, "modelId": row.model_id,
                        "modelVersion": row.model_version, "artifactId": row.artifact_id,
                        "artifactSha256": row.artifact_sha256,
                        "parameterRevision": row.parameter_revision,
                    }]),
                    "modelId": row.model_id, "modelVersion": row.model_version,
                    "artifactId": row.artifact_id, "artifactSha256": row.artifact_sha256,
                    "parameterRevision": row.parameter_revision, "expiresAt": expires_at}
                if expires_at <= datetime.now(timezone.utc) and not stopping:
                    row.revoked_at = datetime.now(timezone.utc)
                    reject("runtime_grant_expired", "runtime grant has expired", 403)
                if expected_scope and any(scope.get(key) != value for key, value in expected_scope.items()):
                    reject("runtime_grant_scope_mismatch", "runtime grant scope does not match", 403)
                row.revoked_at = datetime.now(timezone.utc)
                row.last_used_at = datetime.now(timezone.utc)
                return scope
        with self._lock:
            lease = self._leases.get(key) or (self._stopped.get(key) if stopping else None)
            if lease is None:
                reject("runtime_grant_invalid", "runtime grant is invalid or revoked", 403)
            if lease["expiresAt"] <= datetime.now(timezone.utc) and not stopping:
                self._leases.pop(key, None)
                reject("runtime_grant_expired", "runtime grant has expired", 403)
            if expected_scope and any(lease.get(key) != value for key, value in expected_scope.items()):
                reject("runtime_grant_scope_mismatch", "runtime grant scope does not match", 403)
            self._leases.pop(key, None)
            if stopping:
                self._stopped = {digest: item for digest, item in self._stopped.items()
                                 if item["expiresAt"] > datetime.now(timezone.utc) - timedelta(days=1)}
                self._stopped[key] = deepcopy(lease)
            return deepcopy(lease)

    def revoke(self, token):
        if token:
            key = self._key(token)
            if self.database is not None and self.database.enabled:
                with self.database.session() as session:
                    row = session.scalar(select(ProjectSceneRuntimeGrantRecord).where(
                        ProjectSceneRuntimeGrantRecord.token_digest == key).with_for_update())
                    if row is not None and row.revoked_at is None:
                        row.revoked_at = datetime.now(timezone.utc)
            else:
                with self._lock:
                    self._leases.pop(key, None)


class SceneInstallationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: StrictInt = Field(ge=1)
    target: Literal["pc", "mobile"]
    planId: str | None = Field(default=None, min_length=1, max_length=128)
    memberIds: list[str] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.planId and self.memberIds:
            raise ValueError("installation selects either planId or memberIds")
        if self.memberIds and len(set(self.memberIds)) != len(self.memberIds):
            raise ValueError("memberIds must be unique")
        return self


class ProjectScenes:
    def __init__(self, database_manager, catalog, assignments):
        self.database = database_manager
        self.catalog = catalog
        self.assignments = assignments
        self._memory = {}
        self._installation_memory = {}
        self._runtime_grants = SceneRuntimeGrant(database_manager)
        self._lock = _scene_lock
        self._removal_operations = {}

    @property
    def persistent(self):
        return self.database is not None and self.database.enabled

    @staticmethod
    def _public(row, members, plans=None, plan_members=None):
        member_payload = [{"memberId": m.member_id, "projectModelId": m.project_model_id,
                           "modelId": m.model_id, "version": m.model_version,
                           "target": m.target, "position": m.position,
                           "inputTypes": deepcopy(m.input_types or row.input_types), "execution": m.execution,
                           "parameterRevision": m.parameter_revision,
                           **({"parameterSnapshot": deepcopy(m.parameter_snapshot)} if m.parameter_snapshot else {})}
                          for m in sorted(members, key=lambda m: m.position)]
        by_plan = {}
        if plans:
            for plan in plans:
                selected = sorted((item for item in (plan_members or [])
                                   if item.plan_id == plan.plan_id), key=lambda item: item.position)
                by_plan[plan.plan_id] = {
                    "planId": plan.plan_id, "name": plan.display_name,
                    "inputTypes": deepcopy(plan.input_types),
                    "memberIds": [item.member_id for item in selected],
                    "execution": plan.execution, "enabled": plan.enabled,
                    "cameraPolicy": CameraPolicy.model_validate(plan.camera_policy or {}).model_dump(),
                    **({"parameterSources": deepcopy(plan.parameter_sources)} if plan.parameter_sources else {})}
        if not by_plan and len(member_payload) == 1:
            member = member_payload[0]
            by_plan["default"] = {"planId": "default", "name": "默认方案",
                "inputTypes": deepcopy(member["inputTypes"]), "memberIds": [member["memberId"]],
                "execution": "single", "enabled": True, "implicit": True}
        return {
            "projectId": row.project_id, "sceneId": row.scene_id, "name": row.display_name,
            "inputTypes": deepcopy(row.input_types), "enabled": row.enabled,
            "approved": row.approved, "revision": row.revision,
            "suiteContractVersion": 2, "models": member_payload, "plans": list(by_plan.values()),
            **({"deletedAt": row.deleted_at.isoformat(), "deletionOperationId": row.deletion_operation_id}
               if row.deleted_at else {}),
        }

    def _read(self, session, project_id, scene_id):
        if session is None:
            return deepcopy(self._memory.get((project_id, scene_id)))
        rows = session.execute(select(ProjectSceneRecord, ProjectSceneMemberRecord).outerjoin(
            ProjectSceneMemberRecord,
            (ProjectSceneMemberRecord.project_id == ProjectSceneRecord.project_id)
            & (ProjectSceneMemberRecord.scene_id == ProjectSceneRecord.scene_id)).where(
                ProjectSceneRecord.project_id == project_id, ProjectSceneRecord.scene_id == scene_id)).all()
        if not rows:
            return None
        scene_row = rows[0][0]
        plans = session.scalars(select(ProjectScenePlanRecord).where(
            ProjectScenePlanRecord.project_id == project_id,
            ProjectScenePlanRecord.scene_id == scene_id).order_by(ProjectScenePlanRecord.plan_id)).all()
        plan_members = session.scalars(select(ProjectScenePlanMemberRecord).where(
            ProjectScenePlanMemberRecord.project_id == project_id,
            ProjectScenePlanMemberRecord.scene_id == scene_id)).all()
        return self._public(scene_row, [member for _, member in rows if member is not None], plans, plan_members)

    def list(self, project_id):
        with self._lock:
            if self.persistent:
                with self.database.session() as session:
                    ids = session.scalars(select(ProjectSceneRecord.scene_id).where(
                        ProjectSceneRecord.project_id == project_id).order_by(ProjectSceneRecord.scene_id)).all()
                    rows = [self._read(session, project_id, scene_id) for scene_id in ids]
            else:
                rows = [deepcopy(row) for (pid, _), row in self._memory.items() if pid == project_id]
            for row in rows:
                if "plans" not in row:
                    row["plans"] = []
                if not row["plans"] and len(row.get("models", [])) == 1:
                    member = row["models"][0]
                    row["plans"] = [{"planId": "default", "name": "默认方案",
                        "inputTypes": deepcopy(member.get("inputTypes", row.get("inputTypes", ["image"]))),
                        "memberIds": [member.get("memberId") or _derived_member_id(member["projectModelId"])],
                        "execution": "single", "enabled": True, "implicit": True}]
                for plan in row["plans"]:
                    plan["cameraPolicy"] = CameraPolicy.model_validate(plan.get("cameraPolicy", {})).model_dump()
            return sorted(rows, key=lambda row: row["sceneId"])

    def get(self, project_id, scene_id):
        return next((row for row in self.list(project_id) if row["sceneId"] == scene_id), None)

    @staticmethod
    def normalize_members(models, scene_input_types):
        normalized = []
        for member in models:
            item = deepcopy(member)
            item["memberId"] = item.get("memberId") or _derived_member_id(item["projectModelId"])
            item["inputTypes"] = list(item.get("inputTypes") or scene_input_types)
            if len(set(item["inputTypes"])) != len(item["inputTypes"]):
                reject("invalid_scene_suite", "member inputTypes must be unique", 422)
            normalized.append(item)
        if len({item["memberId"] for item in normalized}) != len(normalized):
            reject("invalid_scene_suite", "duplicate memberId", 422)
        return normalized

    def resolve_inventory_members(self, session, project_id, models, input_types):
        resolved = []
        seen = set()
        for member in models:
            project_model_id = member["projectModelId"]
            if project_model_id in seen:
                reject("duplicate_project_model", "a project model may appear only once in a scene", 422)
            seen.add(project_model_id)
            assignment = self.assignments.resolve(
                project_id, project_model_id, session=session, lock=session is not None, enabled_only=False
            )
            if assignment is None:
                reject("project_model_not_found", "project model is not assigned to this project", 404)
            if not assignment["enabled"]:
                reject("project_model_disabled", "disabled project models cannot be scene members")
            requested_revision = member.get("parameterRevision")
            if requested_revision is not None and requested_revision != assignment["parameterRevision"]:
                reject("project_model_revision_conflict", "project model parameter revision was changed")
            snapshot = assignment.get("parameterSnapshot")
            expected_platform = assignment["parameterPlatform"]
            if not isinstance(snapshot, dict) or not (
                snapshot.get("projectId") == project_id
                and snapshot.get("modelId") == assignment["modelId"]
                and snapshot.get("modelVersion") == assignment["modelVersion"]
                and snapshot.get("platform") == expected_platform
                and snapshot.get("revision") == assignment["parameterRevision"]
            ):
                reject("project_model_snapshot_invalid", "project model parameter snapshot is invalid")
            item = deepcopy(member)
            item.update(
                modelId=assignment["modelId"],
                version=assignment["modelVersion"], target=assignment["target"],
                parameterRevision=assignment["parameterRevision"],
                inventoryParameterSnapshot=deepcopy(snapshot),
            )
            item["inputTypes"] = list(item.get("inputTypes") or input_types)
            resolved.append(item)
        return resolved

    @staticmethod
    def normalize_plans(plans, models, scene_input_types):
        members = {member["memberId"]: member for member in models}
        normalized = []
        seen = set()
        for plan in plans or []:
            item = deepcopy(plan)
            item["cameraPolicy"] = CameraPolicy.model_validate(item.get("cameraPolicy", {})).model_dump()
            if item["planId"] in seen:
                reject("invalid_scene_suite", "duplicate planId", 422)
            seen.add(item["planId"])
            ids = item["memberIds"]
            if len(set(ids)) != len(ids) or any(member_id not in members for member_id in ids):
                reject("invalid_scene_suite", "plan references a missing or duplicate memberId", 422)
            if not set(item["inputTypes"]).issubset(set(scene_input_types)):
                reject("scene_input_not_supported", "plan input is outside the scene input declaration")
            if item["execution"] == "single" and len(ids) != 1:
                reject("invalid_scene_suite", "single plan must select exactly one member", 422)
            for member_id in ids:
                if not set(item["inputTypes"]).issubset(set(members[member_id]["inputTypes"])):
                    reject("scene_input_not_supported", "plan input is not supported by the selected member")
            normalized.append(item)
        return normalized

    def validate_models(self, models, input_types):
        for member in models:
            try:
                model = self.catalog.get(member["modelId"], member["version"])
            except KeyError:
                reject("model_not_found", "exact model release not found", 404)
            target = member["target"]
            if model.get("status") != "PUBLISHED" or not model.get("releaseEligible"):
                reject("model_not_published", "scene members must be published releases")
            if target not in model.get("supportedTargets", []):
                reject("model_target_not_supported", "member target is not supported")
            if not model.get("targetReadiness", {}).get(target, {}).get("ready"):
                reject("model_target_not_ready", "member artifact is not ready")
            if not project_target_usable(model, target):
                reject("model_target_not_published", "member target is not published")
            member_inputs = member.get("inputTypes", input_types)
            if any(kind not in input_types for kind in member_inputs):
                reject("scene_input_not_supported", "member input is outside the scene input declaration")
            supported_inputs = model.get("inputTypes", ["image", "video"])
            if any(kind not in supported_inputs for kind in member_inputs):
                reject("scene_input_not_supported", "member does not support the scene input type")

    @staticmethod
    def reviewed_parameters(scene, member):
        """Only server-frozen parameters for this exact approval grant execution."""
        profile = member.get("parameterSnapshot")
        platform = "android" if member["target"] == "mobile" else "server"
        if not isinstance(profile, dict) or not (
            profile.get("projectId") == scene["projectId"]
            and profile.get("modelId") == member["modelId"]
            and profile.get("modelVersion") == member["version"]
            and profile.get("platform") == platform
            and type(profile.get("revision")) is int and profile["revision"] >= 0
            and isinstance(profile.get("detection"), dict)
            and isinstance(profile.get("alertRules"), list)
        ):
            return None
        return deepcopy(profile)

    @staticmethod
    def validate_approval_parameters(scene, member):
        """Reject broken inventory snapshots before creating an approval revision.

        Do not infer missing metadata or fetch current parameters: the assignment
        snapshot is the sole input to the explicit scene approval.
        """
        profile = ProjectScenes.reviewed_parameters(scene, member)
        invalid = []
        if profile is None:
            invalid.append("identityOrValues")
        else:
            if type(profile.get("schemaVersion")) is not int or profile["schemaVersion"] != 2:
                invalid.append("schemaVersion")
            source = profile.get("source")
            if not isinstance(source, str) or source not in {"default", "custom", "inherited"}:
                invalid.append("source")
            if "updatedAt" not in profile or not (profile["updatedAt"] is None or
                    isinstance(profile["updatedAt"], str) and profile["updatedAt"].strip()):
                invalid.append("updatedAt")
            revision = profile.get("revision")
            if type(revision) is not int or revision != member["parameterRevision"]:
                invalid.append("revision")
            inherited = profile.get("inheritedRevision")
            if ((source == "inherited" and (type(inherited) is not int or inherited < 0))
                    or (source != "inherited" and inherited is not None)):
                invalid.append("inheritedRevision")
        if invalid:
            target = "移动端" if member["target"] == "mobile" else "PC端"
            raise HTTPException(409, detail={
                "code": "project_model_snapshot_invalid",
                "message": (f"项目模型 {member['modelId']} / {member['version']}（{target}）的参数快照不完整或格式错误，"
                            "请在“项目模型”重新批准该条分配，再审批场景"),
                "memberId": member["memberId"], "projectModelId": member["projectModelId"],
                "modelId": member["modelId"], "modelVersion": member["version"],
                "target": member["target"], "invalidFields": invalid,
            })

    def list_catalog(self, project_id, *, manage=False, target=None, input_type=None):
        active = self.assignments.project_active(project_id)
        results = []
        for scene in self.list(project_id):
            if scene.get("deletedAt"):
                continue
            if input_type and input_type not in scene["inputTypes"]:
                continue
            members = [m for m in scene["models"] if target is None or m["target"] == target]
            if not members:
                continue
            available = bool(active and scene["enabled"] and scene["approved"])
            projected = []
            for member in members:
                ready = {"pc": False, "mobile": False}
                eligible = False
                model = None
                assignment = None
                try:
                    model = self.catalog_model(member)
                    ready = {key: bool(model.get("targetReadiness", {}).get(key, {}).get("ready"))
                             for key in ready}
                    eligible = project_target_usable(model, member["target"])
                    assignment = self.assignments.resolve(project_id, member["projectModelId"], enabled_only=False)
                    eligible = eligible and assignment is not None and assignment["enabled"]
                    eligible = eligible and assignment["modelId"] == member["modelId"]
                    eligible = eligible and assignment["modelVersion"] == member["version"]
                    eligible = eligible and assignment["target"] == member["target"]
                    supported_inputs = model.get("inputTypes", ["image", "video"])
                    eligible = eligible and all(kind in supported_inputs for kind in member.get("inputTypes", scene["inputTypes"]))
                except (KeyError, ValueError, OSError):
                    pass
                available = available and eligible
                projected.append({**member, "modelName": model_display_name(model),
                                  "targetReadiness": ready, "available": eligible})
                if manage and assignment is not None:
                    projected[-1]["pendingParameterSnapshot"] = deepcopy(assignment.get("parameterSnapshot"))
            if not manage and not available:
                continue
            by_target = {key: [m for m in scene["models"] if m["target"] == key] for key in ("pc", "mobile")}
            execution_by_target = {key: len(rows) == 1 and rows[0]["execution"] == "single"
                                   for key, rows in by_target.items()}
            execution_supported = (execution_by_target[target] if target else
                                   all(execution_by_target[key] for key, rows in by_target.items() if rows))
            plans = [plan for plan in scene.get("plans", [])
                     if target is None or any(member_id in {m["memberId"] for m in projected}
                                             for member_id in plan.get("memberIds", []))]
            results.append({**scene, "models": projected, "plans": plans, "available": available,
                "executionContractVersion": 1,
                "executionSupported": execution_supported, "executionSupportByTarget": execution_by_target})
            for member in projected:
                member["artifacts"] = []
                profile = self.reviewed_parameters(scene, member)
                member["executionReady"] = bool(available and profile)
                if profile:
                    member.update(parameterPlatform=profile["platform"], parameterRevision=profile["revision"])
                if not available:
                    continue
                model = self.catalog_model(member)
                prefix = (f"/aiyoloapi/projects/{quote(project_id, safe='')}/scenes/{quote(scene['sceneId'], safe='')}/"
                          f"models/{quote(member['modelId'], safe='')}/versions/{quote(member['version'], safe='')}/artifacts/")
                member["artifacts"] = [{key: artifact[key] for key in
                    ("artifactId", "format", "platform", "target", "sizeBytes", "sha256", "contentType", "exists", "hashValid") if key in artifact}
                    | {"url": prefix + quote(artifact["artifactId"], safe="") + "/download"}
                    for artifact in model.get("artifacts", []) if artifact.get("target") == member["target"]]
                if profile:
                    # Reuse the public catalog contract, but never retain global/assignment URLs.
                    release = {key: deepcopy(value) for key, value in model.items()
                               if key not in {"artifacts", "downloadUrl", "url", "versionedUrl"}}
                    release["artifacts"] = [{**artifact, "url": artifact["url"] +
                        f"?expectedRevision={scene['revision']}"} for artifact in member["artifacts"]]
                    member["executionModel"] = release
                    member["parameterUrl"] = (f"/aiyoloapi/projects/{quote(project_id, safe='')}/scenes/"
                        f"{quote(scene['sceneId'], safe='')}/models/{quote(member['modelId'], safe='')}/"
                        f"versions/{quote(member['version'], safe='')}/parameters?target={member['target']}"
                        f"&expectedRevision={scene['revision']}")
        return results

    def catalog_model(self, member):
        return self.catalog.get(member["modelId"], member["version"])

    def visible(self, project_id, scene_id, *, manage=False, target=None, input_type=None):
        scene = next((row for row in self.list_catalog(project_id, manage=manage, target=target, input_type=input_type)
                      if row["sceneId"] == scene_id), None)
        if scene is None:
            reject("scene_not_found", "scene not found", 404)
        return scene

    def artifact(self, project_id, scene_id, model_id, version, artifact_id, expected_revision=None):
        # Never use management visibility for a download. Approval is required even for owners.
        try:
            model = self.catalog.get(model_id, version)
        except (KeyError, ValueError, OSError):
            reject("model_not_project_authorized", "release is unavailable", 404)
        artifact = next((a for a in model["artifacts"] if a["artifactId"] == artifact_id), None)
        if artifact is None:
            reject("model_not_project_authorized", "artifact not found", 404)
        scene = self.visible(project_id, scene_id, target=artifact.get("target"))
        if expected_revision is not None and scene["revision"] != expected_revision:
            reject("revision_conflict", "scene revision was changed")
        if not any(a["modelId"] == model_id and a["version"] == version
                   and a["target"] == artifact.get("target") for a in scene["models"]):
            reject("model_not_project_authorized", "artifact target is not approved in this scene", 404)
        try:
            member = next(a for a in scene["models"] if a["modelId"] == model_id
                          and a["version"] == version and a["target"] == artifact.get("target"))
            self._validated_artifacts(member)
            return self.catalog.get_artifact(model_id, artifact_id, version)
        except (KeyError, ValueError, OSError):
            reject("model_target_not_ready", "artifact is unavailable")

    def parameters(self, project_id, scene_id, model_id, version, target, expected_revision):
        scene = self.visible(project_id, scene_id, target=target)
        if scene["revision"] != expected_revision:
            reject("revision_conflict", "scene revision was changed")
        member = next((m for m in scene["models"] if m["modelId"] == model_id
                       and m["version"] == version and m["target"] == target), None)
        if member is None:
            reject("model_not_project_authorized", "release is not approved in this scene", 404)
        self._validated_artifacts(member)
        profile = self.reviewed_parameters(scene, member)
        if profile is None:
            reject("scene_parameters_not_approved", "scene needs parameter review before execution")
        return {**profile, "sceneId": scene_id, "sceneRevision": scene["revision"]}

    @staticmethod
    def _selection(scene, target, plan_id=None, member_ids=None):
        target_members = [member for member in scene.get("models", []) if member["target"] == target]
        by_id = {member["memberId"]: member for member in target_members}
        if plan_id:
            plan = next((item for item in scene.get("plans", []) if item["planId"] == plan_id), None)
            if plan is None or not plan.get("enabled", True):
                reject("plan_not_found", "plan not found", 404)
            selected_ids = list(plan["memberIds"])
            selection = {"type": "plan", "planId": plan_id}
        elif member_ids:
            selected_ids = list(member_ids)
            selection = {"type": "members", "memberIds": selected_ids}
        else:
            selected_ids = [member["memberId"] for member in target_members]
            selection = {"type": "suite"}
        if not selected_ids:
            reject("model_target_not_project_authorized", "no member is authorized for this target", 404)
        if len(set(selected_ids)) != len(selected_ids) or any(member_id not in by_id for member_id in selected_ids):
            reject("model_target_not_project_authorized", "installation member is not authorized for this target", 404)
        return [by_id[member_id] for member_id in selected_ids], selection

    def _validated_artifacts(self, member):
        """Re-read release lifecycle, signature and bytes for one exact member."""
        try:
            model = self.catalog.get(member["modelId"], member["version"])
        except (KeyError, ValueError, OSError):
            reject("model_target_not_ready", "exact model release is unavailable")
        if (model.get("status") != "PUBLISHED" or not model.get("releaseEligible")
                or not project_target_usable(model, member["target"])):
            reject("model_target_not_ready", "model target is no longer published")
        artifacts = [artifact for artifact in model.get("artifacts", [])
                     if artifact.get("target") == member["target"]
                     or (member["target"] == "pc" and artifact.get("platform") == "server")
                     or (member["target"] == "mobile" and artifact.get("platform") == "android")]
        if not artifacts:
            reject("model_target_not_ready", "target artifact is missing")
        # Mobile packages require a trusted signed manifest. PC artifacts keep
        # legacy unsigned development releases compatible, but explicit invalid
        # signatures are never accepted.
        signature_status = str(model.get("signatureStatus", "unsigned")).lower()
        if member["target"] == "mobile" and signature_status != "signed":
            reject("model_target_not_ready", "target artifact signature is not valid")
        if signature_status in {"invalid", "tampered", "revoked"}:
            reject("model_target_not_ready", "target artifact signature is not valid")
        projected = []
        for declared in artifacts:
            try:
                artifact, _path = self.catalog.get_artifact(member["modelId"], declared["artifactId"], member["version"])
            except (KeyError, ValueError, OSError):
                reject("model_target_not_ready", "target artifact integrity check failed")
            item = {key: deepcopy(value) for key, value in artifact.items()
                    if key in {"artifactId", "format", "platform", "target", "sizeBytes", "sha256", "contentType"}}
            item.update(target=member["target"], exists=True, hashValid=True)
            projected.append(item)
        projected.sort(key=lambda item: (0 if item.get("format") in ({"mobile": {"tflite"}, "pc": {"pt", "onnx"}}[member["target"]]) else 1,
                                         item.get("artifactId", "")))
        return model, projected

    def _installation_projection(self, project_id, scene_id, account_id, target, *,
                                  plan_id=None, member_ids=None, persist=False,
                                  context=None, request_id=None):
        scene = self.get(project_id, scene_id)
        if scene is None or not scene.get("enabled") or not scene.get("approved"):
            reject("scene_not_found", "scene not found", 404)
        if not self.assignments.project_active(project_id):
            reject("project_inactive", "project is not active", 403)
        selected, selection = self._selection(scene, target, plan_id, member_ids)
        required = [member["memberId"] for member in selected]
        ready = []
        members = []
        failures = []
        for member in selected:
            try:
                _model, artifacts = self._validated_artifacts(member)
            except HTTPException as exc:
                failures.append(exc.detail)
                members.append({key: deepcopy(value) for key, value in member.items()
                                if key not in {"parameterSnapshot"}} | {"artifacts": [], "available": False})
                continue
            ready.append(member["memberId"])
            public_member = {key: deepcopy(value) for key, value in member.items()
                             if key not in {"parameterSnapshot", "execution"}}
            public_member.update(artifacts=artifacts, available=True)
            members.append(public_member)
        status = "ready" if len(ready) == len(required) else ("partial" if ready else "blocked")
        selection_key = (f"plan:{plan_id}" if plan_id else
                         f"members:{','.join(sorted(member_ids))}" if member_ids else "suite")
        result = {
            "projectId": project_id, "sceneId": scene_id, "revision": scene["revision"],
            "target": target, "selection": selection,
            "requiredMemberIds": required, "readyMemberIds": ready, "status": status,
            "members": members,
            "installationAuthorized": True,
            "runtimeAuthorization": False,
            "runtimeGrant": None,
        }
        if failures:
            result["errors"] = failures
        if persist and self.persistent:
            with self.database.session() as session:
                account = session.get(AccountRecord, account_id)
                membership = session.get(ProjectMembershipRecord, (project_id, account_id))
                if account is None or not account.enabled or (
                        account.platform_role != "PLATFORM_ADMIN"
                        and (membership is None or not membership.enabled)):
                    reject("project_capability_required", "account is not active", 403)
                row = session.get(ProjectSceneInstallationRecord,
                    (project_id, scene_id, account_id, target, scene["revision"], selection_key))
                if row is None:
                    row = ProjectSceneInstallationRecord(
                        project_id=project_id, scene_id=scene_id, account_id=account_id,
                        target=target, revision=scene["revision"], selection_key=selection_key)
                    session.add(row)
                row.plan_id = plan_id
                row.member_id = (member_ids[0] if member_ids and len(member_ids) == 1 else None)
                row.required_member_ids = required
                row.ready_member_ids = ready
                row.status = status
                row.last_error = failures[0] if failures else None
                session.flush()
                audit_change(session, context, request_id, "scene.installation.prepare",
                             "scene_installation", selection_key, None, result)
        elif persist:
            self._installation_memory[(project_id, scene_id, account_id, target, scene["revision"], selection_key)] = deepcopy(result)
            audit_change(None, context, request_id, "scene.installation.prepare",
                         "scene_installation", selection_key, None, result)
        return result

    def installation(self, project_id, scene_id, account_id, target, *, plan_id=None, member_ids=None):
        return self._installation_projection(project_id, scene_id, account_id, target,
                                              plan_id=plan_id, member_ids=member_ids, persist=False)

    def prepare_installation(self, project_id, scene_id, account_id, target, expected_revision, *,
                             plan_id=None, member_ids=None, context=None, request_id=None):
        scene = self.get(project_id, scene_id)
        if scene is None:
            reject("scene_not_found", "scene not found", 404)
        if scene["revision"] != expected_revision:
            reject("revision_conflict", "scene revision was changed")
        return self._installation_projection(project_id, scene_id, account_id, target,
                                              plan_id=plan_id, member_ids=member_ids, persist=True,
                                              context=context, request_id=request_id)

    def resolve_plan(self, project_id, scene_id, plan_id, body):
        scene = self.visible(project_id, scene_id, target=body.target, input_type=body.inputType)
        if scene["revision"] != body.expectedRevision:
            reject("revision_conflict", "scene revision was changed")
        if body.clientContractVersion < 2:
            reject("execution_mode_not_supported", "client does not support scene suite plans")
        plan = next((item for item in scene.get("plans", []) if item["planId"] == plan_id), None)
        if plan is None or not plan.get("enabled", True):
            reject("plan_not_found", "plan not found", 404)
        if body.inputType not in plan["inputTypes"]:
            reject("scene_input_not_supported", "plan does not support input type")
        by_id = {member["memberId"]: member for member in scene["models"]
                 if member["target"] == body.target}
        selected = [by_id[member_id] for member_id in plan["memberIds"] if member_id in by_id]
        if len(selected) != len(plan["memberIds"]):
            reject("model_target_not_project_authorized", "plan member target is not available", 404)
        multi_member = plan["execution"] != "single" or len(selected) != 1
        if multi_member and (body.clientContractVersion < 3
                             or plan["execution"] not in body.supportedExecutionModes):
            reject("execution_mode_not_supported", "client contract or declared capabilities do not support plan mode")
        resolved_members = []
        for member in selected:
            if not member.get("executionReady"):
                reject("scene_parameters_not_approved", "scene needs parameter review before execution")
            _model, artifacts = self._validated_artifacts(member)
            source = next((item for item in plan.get("parameterSources", [])
                           if item.get("planId", plan_id) == plan_id
                           and item.get("memberId") == member["memberId"]), None)
            profile = deepcopy(source.get("parameterSnapshot")) if source else self.reviewed_parameters(scene, member)
            if not isinstance(profile, dict) or not (
                    profile.get("projectId") == project_id
                    and profile.get("modelId") == member["modelId"]
                    and profile.get("modelVersion") == member["version"]
                    and profile.get("platform") == ("android" if member["target"] == "mobile" else "server")
                    and type(profile.get("revision")) is int
                    and isinstance(profile.get("detection"), dict)
                    and isinstance(profile.get("alertRules"), list)):
                reject("scene_parameters_not_approved", "plan parameters are not approved")
            primary = artifacts[0]
            resolved_member = {key: deepcopy(value) for key, value in member.items()
                               if key != "parameterSnapshot"}
            resolved_member.update({
                "artifacts": artifacts, "artifactId": primary["artifactId"],
                "artifactSha256": primary["sha256"], "parameterPlatform": profile["platform"],
                "parameterRevision": profile["revision"], "parameterSnapshot": profile,
            })
            resolved_members.append(resolved_member)
        if plan["execution"] == "single" and len(resolved_members) != 1:
            reject("execution_mode_not_supported", "single plan must resolve exactly one member")
        first = resolved_members[0]
        return {"projectId": project_id, "sceneId": scene_id, "revision": scene["revision"],
                "planId": plan_id, "execution": plan["execution"], "inputType": body.inputType,
                "cameraPolicy": deepcopy(plan["cameraPolicy"]),
                "target": body.target, "resolveContractVersion": 3 if multi_member else 2,
                "supportedExecutionModes": [plan["execution"]], "members": resolved_members,
                "memberId": first["memberId"], "modelId": first["modelId"],
                "modelVersion": first["version"], "artifactId": first["artifactId"],
                "artifactSha256": first["artifactSha256"], "parameterRevision": first["parameterRevision"],
                "resolutionOnly": True, "runtimeAuthorization": False}

    def _audit_runtime_grant(self, context, request_id, operation, scene_id, plan_id, result, session=None):
        if context is None:
            return
        after = {key: value for key, value in result.items() if key != "runtimeGrant"}
        args = (context, request_id, f"scene.runtime_grant.{operation}",
                "scene_runtime_grant", f"{scene_id}:{plan_id}", None, after)
        if session is not None:
            audit_change(session, *args)
        elif self.persistent:
            with self.database.session() as session:
                audit_change(session, *args)
        else:
            audit_change(None, *args)

    def runtime_grant(self, project_id, scene_id, plan_id, account_id, body, *, context=None, request_id=None, idempotency_key=None):
        # Same project locks as approval/membership writers. Token rotation, new
        # scope and audit commit together; failed revalidation consumes the old
        # token, so a later re-enable cannot resurrect it.
        from .model_catalog import _mutation_lock as catalog_lock
        from .project_management import _mutation_lock as management_lock
        error = None
        with self._lock, catalog_lock, management_lock:
            if not self.persistent:
                before = deepcopy((self._runtime_grants._leases, self._runtime_grants._stopped,
                                   self._runtime_grants._requests))
                try:
                    return self._runtime_grant(project_id, scene_id, plan_id, account_id, body,
                        context=context, request_id=request_id, idempotency_key=idempotency_key)
                except HTTPException:
                    raise
                except Exception:
                    (self._runtime_grants._leases, self._runtime_grants._stopped,
                     self._runtime_grants._requests) = before
                    raise
            try:
                with self.database.session() as session:
                    lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
                    lock_project(session, project_id, enforce_lifecycle=False)
                    # Serialize with disable/demotion of this account without
                    # locking unrelated accounts or reversing their lock order.
                    session.scalar(select(AccountRecord).where(
                        AccountRecord.account_id == account_id).with_for_update())
                    try:
                        result = self._runtime_grant(project_id, scene_id, plan_id, account_id, body,
                            context=context, request_id=request_id, idempotency_key=idempotency_key, session=session)
                    except HTTPException as exc:
                        error = exc
            except IntegrityError as exc:
                if "request_digest" not in str(exc) and "uq_scene_runtime_grant_request" not in str(exc):
                    raise
                reject("runtime_grant_request_replayed", "runtime grant request was already processed", 409)
        if error is not None:
            raise error
        return result

    def _runtime_grant(self, project_id, scene_id, plan_id, account_id, body, *, context=None, request_id=None, idempotency_key=None, session=None):
        resolution_body = ScenePlanResolution(**body.model_dump(exclude={"grantToken", "operation"}))
        scope = {"accountId": account_id, "projectId": project_id, "sceneId": scene_id,
                 "planId": plan_id, "expectedRevision": body.expectedRevision, "target": body.target,
                 "inputType": body.inputType, "clientContractVersion": body.clientContractVersion,
                 "supportedExecutionModes": list(body.supportedExecutionModes)}
        operation = body.operation
        previous = self._runtime_grants.get(body.grantToken, scope, session=session,
            stopping=operation == "stop") if operation != "start" else None
        if operation == "start" and body.grantToken:
            reject("runtime_grant_operation_invalid", "start must not reuse a runtime grant", 422)
        if operation != "start" and previous is None:
            reject("runtime_grant_invalid", "runtime grant is invalid or revoked", 403)
        if operation == "stop":
            result = {"operation": "stop", "runtimeAuthorization": False, "runtimeGrant": None,
                      "runtimeGrantContractVersion": 2}
            self._audit_runtime_grant(context, request_id, operation, scene_id, plan_id, result, session)
            return result
        authority = self._runtime_authority(project_id, account_id, context, session) if context is not None else {}
        if previous and previous.get("authority", {}) != authority:
            reject("runtime_grant_scope_mismatch", "runtime authority generation changed", 403)
        resolution = self.resolve_plan(project_id, scene_id, plan_id, resolution_body)
        for member in resolution["members"]:
            guard_model_write(session, self.catalog, member["modelId"], member["version"])
        members = [{"memberId": member["memberId"], "modelId": member["modelId"],
                    "modelVersion": member["version"], "artifactId": member["artifactId"],
                    "artifactSha256": member["artifactSha256"],
                    "parameterRevision": member["parameterRevision"],
                    "parameterSha256": parameter_digest(member["parameterSnapshot"]),
                    "target": body.target,
                    "artifacts": [{key: artifact[key] for key in ("artifactId", "sha256", "sizeBytes")}
                                  for artifact in member["artifacts"]]}
                   for member in resolution["members"]]
        if previous:
            old_members = previous.get("members", [])
            # Pre-M39 single leases have no parameter digest/full artifact set.
            # Revalidate their original exact fields once, then upgrade to the
            # complete snapshot. They can never become a multi-member lease.
            legacy = len(old_members) == 1 and "parameterSha256" not in old_members[0]
            matched = (len(members) == 1 and all(members[0].get(key) == value
                for key, value in old_members[0].items())) if legacy else old_members == members
            if previous.get("execution") != resolution["execution"] or not matched:
                reject("runtime_grant_scope_mismatch", "resolved plan member snapshot changed", 403)
        member = resolution["members"][0]
        scope.update({"memberId": member["memberId"], "modelId": member["modelId"],
                      "modelVersion": member["version"], "artifactId": member["artifactId"],
                      "artifactSha256": member["artifactSha256"],
                      "parameterRevision": member["parameterRevision"],
                      "execution": resolution["execution"], "members": members, "authority": authority})
        replay_key = idempotency_key or request_id
        request_digest = sha256(json.dumps([account_id, project_id, scene_id, plan_id,
            replay_key], separators=(",", ":")).encode()).hexdigest() if replay_key else None
        token, expires_at = self._runtime_grants.issue(scope, session=session, request_digest=request_digest)
        result = {"operation": operation, "runtimeAuthorization": True,
                  "runtimeGrantContractVersion": 2,
                  "runtimeGrant": token, "expiresAt": expires_at.isoformat(),
                  "scope": scope}
        self._audit_runtime_grant(context, request_id, operation, scene_id, plan_id, result, session)
        return result

    def _runtime_authority(self, project_id, account_id, context, session):
        if account_id != context.principal.account_id:
            reject("runtime_grant_scope_mismatch", "account does not match authenticated principal", 403)
        if session is not None:
            account = session.get(AccountRecord, account_id)
            project = session.get(ProjectRecord, project_id)
            membership = session.get(ProjectMembershipRecord, (project_id, account_id))
            admin = account is not None and account.platform_role == "PLATFORM_ADMIN"
            member = membership is not None and membership.enabled and membership.project_role in {"PROJECT_OWNER", "PROJECT_USER"}
            if account is None or not account.enabled or not (admin or member):
                reject("capability_required", "runtime authority was revoked", 403)
            if project is None or project.lifecycle_state != "ACTIVE":
                reject("project_inactive", "project is not active", 403)
            return {"accountRevision": account.revision, "platformRole": account.platform_role,
                "projectRevision": project.revision,
                "membershipRevision": membership.revision if membership is not None else None,
                "membershipCreatedAt": membership.created_at.isoformat() if membership is not None else None}
        else:
            from .project_auth import resolve_project_context
            from .project_management import _memory_account, _memory_memberships
            account = _memory_account(account_id)
            if account is None or not account.enabled:
                reject("capability_required", "account is disabled", 403)
            latest = resolve_project_context(context.principal, project_id)
            if PROJECT_INSPECTION_USE not in latest.capabilities:
                reject("capability_required", "runtime authority was revoked", 403)
            membership = _memory_memberships.get((project_id, account_id))
            return {"accountRevision": account.revision, "platformRole": account.platform_role,
                "projectRevision": latest.project_revision, "membershipRevision": latest.membership_revision,
                "membershipCreatedAt": membership.created_at.isoformat() if membership is not None else None}

    def references(self, model_id, version=None, *, include_inactive=False):
        if self.persistent:
            with self.database.session() as session:
                query = select(ProjectSceneMemberRecord).join(ProjectSceneRecord,
                    (ProjectSceneMemberRecord.project_id == ProjectSceneRecord.project_id)
                    & (ProjectSceneMemberRecord.scene_id == ProjectSceneRecord.scene_id)).where(
                        ProjectSceneMemberRecord.model_id == model_id, ProjectSceneRecord.deleted_at.is_(None))
                if not include_inactive:
                    query = query.where(ProjectSceneRecord.enabled.is_(True), ProjectSceneRecord.approved.is_(True))
                if version is not None:
                    query = query.where(ProjectSceneMemberRecord.model_version == version)
                return [{"projectId": m.project_id, "sceneId": m.scene_id, "memberId": m.member_id}
                        for m in session.scalars(query).all()]
        with self._lock:
            return [{"projectId": row["projectId"], "sceneId": row["sceneId"]} for row in self._memory.values()
                    if not row.get("deletedAt") and (include_inactive or row["approved"] and row["enabled"]) and any(m["modelId"] == model_id
                    and (version is None or m["version"] == version) for m in row["models"])]

    def _save(self, session, project_id, scene_id, changes, expected, context, request_id, creating, approval_reason=None, member_profile_update=None):
        if session is not None:
            # Parameter writers lock these same rows; use their global-before-project order.
            lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
            lock_project(session, project_id)
            project = session.get(ProjectRecord, project_id)
            if project is None or project.lifecycle_state != "ACTIVE":
                reject("project_inactive", "project is not active", 403)
        elif not self.assignments.project_active(project_id):
            reject("project_inactive", "project is not active", 403)
        # Recheck authority after taking the same project row lock as membership writers.
        if context is not None:
            capability = PROJECT_SCENES_APPROVE if approval_reason is not None else PROJECT_SCENES_MANAGE
            if session is not None:
                account = session.get(AccountRecord, context.principal.account_id)
                membership = session.get(ProjectMembershipRecord, (project_id, context.principal.account_id))
                admin = account is not None and account.platform_role == "PLATFORM_ADMIN"
                owner = membership is not None and membership.enabled and membership.project_role == "PROJECT_OWNER"
                if account is None or not account.enabled or not (admin or owner):
                    reject("capability_required", "scene write authority was revoked", 403)
            else:
                from .project_auth import resolve_project_context
                latest = resolve_project_context(context.principal, project_id)
                if capability not in latest.capabilities:
                    reject("capability_required", "scene write authority was revoked", 403)
        before = self._read(session, project_id, scene_id)
        if before is None:
            if not creating:
                reject("scene_not_found", "scene not found", 404)
        elif creating:
            reject("scene_id_conflict", "scene ID already exists")
        if before and before.get("deletedAt"):
            reject("scene_removed", "removed scene identity cannot be edited or restored")
        if expected != (before["revision"] if before else 0):
            reject("revision_conflict", "scene revision was changed")
        if member_profile_update is not None:
            self.guard_member_profile_write(session, context, scene_id, member_profile_update[0], expected)
        incoming = deepcopy(changes)
        base = before or {"projectId": project_id, "sceneId": scene_id, "approved": False}
        if before is not None and "inputTypes" in incoming and "models" not in incoming:
            # v1 members inherited the scene-wide input declaration. Preserve that
            # behavior when a legacy scene narrows/expands its scene filter; only a
            # member with an explicitly different v2 declaration keeps its inputs.
            incoming["models"] = deepcopy(before["models"])
            for member in incoming["models"]:
                if set(member.get("inputTypes", before["inputTypes"])) == set(before["inputTypes"]):
                    member["inputTypes"] = deepcopy(incoming["inputTypes"])
        if "models" in incoming:
            incoming["models"] = self.normalize_members(incoming["models"], incoming.get("inputTypes", base.get("inputTypes", [])))
        elif before is not None:
            incoming["models"] = self.normalize_members(before["models"], incoming.get("inputTypes", before["inputTypes"]))
        if "plans" in incoming:
            incoming["plans"] = self.normalize_plans(incoming["plans"], incoming.get("models", base.get("models", [])),
                                                     incoming.get("inputTypes", base.get("inputTypes", [])))
        elif before is not None:
            incoming["plans"] = deepcopy(before.get("plans", []))
            # The compatibility default follows the sole member; it is not an
            # explicit user-authored multi-member plan and must not block a v1 edit.
            defaults = [plan for plan in incoming["plans"] if plan.get("planId") == "default"]
            if len(defaults) == 1 and len(incoming.get("models", [])) == 1:
                defaults[0]["memberIds"] = [incoming["models"][0]["memberId"]]
                defaults[0]["inputTypes"] = deepcopy(incoming["models"][0].get("inputTypes", incoming.get("inputTypes", [])))
        after = {**deepcopy(base), **incoming,
                 "revision": expected + 1}
        approval = approval_reason is not None
        requires_member_authorization = ((approval and after["approved"]) or
            (not approval and (after["enabled"] or "models" in changes or "inputTypes" in changes)))
        overrides = {}
        for member in after["models"]:
            old = next((m for m in (before or {}).get("models", [])
                        if m["memberId"] == member["memberId"] and m["projectModelId"] == member["projectModelId"]), None)
            profile = (old or {}).get("parameterSnapshot") or {}
            if (profile.get("sceneId") == scene_id and profile.get("memberId") == member["memberId"]
                    and "inventoryRevision" in profile):
                overrides[member["memberId"]] = deepcopy(profile)
                # Public member revisions describe the scene override. Inventory
                # authorization still validates its original assignment revision.
                if "models" not in changes and member.get("parameterRevision") == profile["revision"]:
                    member["parameterRevision"] = profile["inventoryRevision"]
        if requires_member_authorization:
            after["models"] = self.resolve_inventory_members(
                session, project_id, after["models"], after["inputTypes"]
            )
        if member_profile_update is not None:
            overrides[member_profile_update[0]] = deepcopy(member_profile_update[1])
        after["plans"] = self.normalize_plans(after.get("plans", []), after["models"], after["inputTypes"])
        if not after["plans"] and len(after["models"]) == 1:
            member = after["models"][0]
            after["plans"] = [{"planId": "default", "name": "默认方案",
                "inputTypes": deepcopy(member["inputTypes"]), "memberIds": [member["memberId"]],
                "execution": "single", "enabled": True}]
        after["plans"] = sorted(self.normalize_plans(after["plans"], after["models"], after["inputTypes"]), key=lambda plan: plan["planId"])
        after["suiteContractVersion"] = 2
        for member in after["models"]:
            if "models" in changes or "plans" in changes or changes.get("approved") is True or (approval_reason is None and after["enabled"]):
                guard_model_write(session, self.catalog, member["modelId"], member["version"])
        if approval and after["approved"] and not after["enabled"]:
            reject("scene_disabled", "disabled scenes cannot be approved")
        # Disabling/revoking must remain possible even if a member was revoked or lost.
        if (approval and after["approved"]) or (not approval and
                (after["enabled"] or "models" in changes or "inputTypes" in changes)):
            self.validate_models(after["models"], after["inputTypes"])
        if not approval:
            after["approved"] = False  # Every config edit invalidates prior approval.
        for member in after["models"]:
            member.pop("parameterSnapshot", None)
            override = overrides.get(member["memberId"])
            if override and (override["inventoryRevision"] == member["parameterRevision"]
                    and override["modelId"] == member["modelId"] and override["modelVersion"] == member["version"]
                    and override["platform"] == ("android" if member["target"] == "mobile" else "server")):
                member["parameterSnapshot"] = override
                member["parameterRevision"] = override["revision"]
            if approval and after["approved"]:
                if "parameterSnapshot" not in member:
                    member["parameterSnapshot"] = deepcopy(member["inventoryParameterSnapshot"])
                self.validate_approval_parameters(after, member)
            member.pop("inventoryParameterSnapshot", None)
        for plan in after.get("plans", []):
            plan.pop("parameterSources", None)
            if approval and after["approved"]:
                plan["parameterSources"] = [{"memberId": member_id,
                    "planId": plan["planId"],
                    "parameterSnapshot": deepcopy(next(m["parameterSnapshot"] for m in after["models"]
                        if m["memberId"] == member_id))} for member_id in plan["memberIds"]]
        action = "scene.approval" if approval else ("scene.create" if creating else "scene.update")
        audit_after = {**after, **({"reason": approval_reason} if approval else {})}
        if session is None:
            audit_change(None, context, request_id, action, "scene", scene_id, before, audit_after)
            self._memory[(project_id, scene_id)] = deepcopy(after)
        else:
            row = session.get(ProjectSceneRecord, (project_id, scene_id))
            if row is None:
                row = ProjectSceneRecord(project_id=project_id, scene_id=scene_id,
                    created_by_account_id=context.principal.account_id if context else None)
                session.add(row)
            row.display_name, row.input_types = after["name"], after["inputTypes"]
            row.enabled, row.approved, row.revision = after["enabled"], after["approved"], after["revision"]
            row.updated_at = datetime.now(timezone.utc)
            session.flush()
            session.execute(delete(ProjectSceneMemberRecord).where(
                ProjectSceneMemberRecord.project_id == project_id, ProjectSceneMemberRecord.scene_id == scene_id))
            session.execute(delete(ProjectScenePlanMemberRecord).where(
                ProjectScenePlanMemberRecord.project_id == project_id, ProjectScenePlanMemberRecord.scene_id == scene_id))
            session.execute(delete(ProjectScenePlanRecord).where(
                ProjectScenePlanRecord.project_id == project_id, ProjectScenePlanRecord.scene_id == scene_id))
            for member in after["models"]:
                session.add(ProjectSceneMemberRecord(project_id=project_id, scene_id=scene_id,
                    member_id=member["memberId"], project_model_id=member["projectModelId"],
                    model_id=member["modelId"], model_version=member["version"], target=member["target"],
                    position=member["position"], execution=member["execution"], input_types=deepcopy(member["inputTypes"]),
                    parameter_revision=member["parameterRevision"],
                    parameter_snapshot=deepcopy(member.get("parameterSnapshot"))))
            plans = after.get("plans", [])
            for plan in plans:
                session.add(ProjectScenePlanRecord(project_id=project_id, scene_id=scene_id,
                    plan_id=plan["planId"], display_name=plan["name"], input_types=deepcopy(plan["inputTypes"]),
                    execution=plan["execution"], enabled=plan["enabled"],
                    camera_policy=deepcopy(plan["cameraPolicy"]),
                    parameter_sources=deepcopy(plan.get("parameterSources"))))
            # These tables intentionally have no ORM relationship configured;
            # flush the plan rows before inserting their FK-backed member rows.
            session.flush()
            for plan in plans:
                for position, member_id in enumerate(plan["memberIds"]):
                    session.add(ProjectScenePlanMemberRecord(project_id=project_id, scene_id=scene_id,
                        plan_id=plan["planId"], member_id=member_id, position=position))
            session.flush()
            audit_change(session, context, request_id, action, "scene", scene_id, before, audit_after)
            from .model_updates.events import add_domain_event
            add_domain_event(session, project_id, 'scene', after)
            add_event(session, f"scene:{project_id}/{scene_id}", after["revision"],
                      {"enabled": after["enabled"], "approved": after["approved"], "action": action})
        return after

    def guard_member_profile_write(self, session, context, scene_id, member_id, revision):
        """Called by the parameter writer after acquiring the project row lock."""
        project_id = context.project_id
        if session is not None:
            project = session.get(ProjectRecord, project_id)
            account = session.get(AccountRecord, context.principal.account_id)
            membership = session.get(ProjectMembershipRecord, (project_id, context.principal.account_id))
            admin = account is not None and account.platform_role == "PLATFORM_ADMIN"
            owner = membership is not None and membership.enabled and membership.project_role == "PROJECT_OWNER"
            if project is None or project.lifecycle_state != "ACTIVE":
                reject("project_inactive", "project is not active", 403)
            if account is None or not account.enabled or not (admin or owner):
                reject("capability_required", "parameter write authority was revoked", 403)
        else:
            from .project_auth import resolve_project_context
            latest = resolve_project_context(context.principal, project_id)
            if not {PROJECT_SCENES_MANAGE, PROJECT_MODELS_ASSIGN}.issubset(latest.capabilities):
                reject("capability_required", "parameter write authority was revoked", 403)
        scene = self._read(session, project_id, scene_id)
        if scene is None:
            reject("scene_not_found", "scene not found", 404)
        if scene.get("deletedAt"):
            reject("scene_removed", "removed scene identity cannot be edited")
        if scene["revision"] != revision:
            reject("revision_conflict", "scene revision was changed")
        member = next((item for item in scene["models"] if item["memberId"] == member_id), None)
        if member is None:
            reject("scene_member_not_found", "scene member not found", 404)
        inventory_member = deepcopy(member)
        override = member.get("parameterSnapshot") or {}
        if override.get("sceneId") == scene_id and override.get("memberId") == member_id:
            inventory_member["parameterRevision"] = override["inventoryRevision"]
        resolved = self.resolve_inventory_members(session, project_id, [inventory_member], scene["inputTypes"])
        self.validate_models(resolved, scene["inputTypes"])

    def removal_impact(self, project_id, scene_id):
        scene = self.get(project_id, scene_id)
        if scene is None:
            reject("scene_not_found", "scene not found", 404)
        return {"messageType": "removal_impact",
            "operationScope": {"kind": "scene", "projectId": project_id, "sceneId": scene_id,
                               "incarnation": scene_id},
            "expectedRevision": scene["revision"],
            "dependentCounts": {"assignments": 0, "scenes": 0, "plans": len(scene.get("plans", [])),
                                "streams": 0, "activeSlots": 0},
            "knownDevices": 0, "unknownDeviceCount": 0, "safeToRemove": not bool(scene.get("deletedAt"))}

    def soft_delete(self, project_id, scene_id, expected, key, *, context, request_id=None):
        from uuid import uuid4
        scope = f"scene:{project_id}/{scene_id}"
        actor = context.principal.account_id
        request_key, request_digest = operation_identity(actor, scope, key, expected)
        with self._lock, self.assignments.parameters._lock:
            if self.persistent:
                self.assignments.parameters._import_legacy_once()
            with (self.database.session() if self.persistent else nullcontext(None)) as session:
                if session is not None:
                    lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
                    lock_project(session, project_id)
                    session.scalar(select(AccountRecord).where(
                        AccountRecord.account_id == actor).with_for_update())
                self.assignments._check_write_authority(session, project_id, context)
                operation = session.scalar(select(ResourceLifecycleOperationRecord).where(
                    ResourceLifecycleOperationRecord.request_key == request_key)) if session is not None else self._removal_operations.get(request_key)
                if operation is not None:
                    saved_digest = operation.request_digest if session is not None else operation["digest"]
                    if saved_digest != request_digest:
                        reject("idempotency_conflict", "idempotency key was used with another expected revision")
                    return deepcopy(operation.result if session is not None else operation["result"])
                before = self._read(session, project_id, scene_id)
                if before is None:
                    reject("scene_not_found", "scene not found", 404)
                if before.get("deletedAt"):
                    reject("scene_removed", "scene identity is already removed")
                if before["revision"] != expected:
                    reject("revision_conflict", "scene revision was changed")
                operation_id = str(uuid4())
                now = datetime.now(timezone.utc)
                timestamp = now.isoformat().replace("+00:00", "Z")
                after = {**deepcopy(before), "enabled": False, "approved": False, "revision": expected + 1,
                         "deletedAt": timestamp, "deletionOperationId": operation_id}
                result = {"operationId": operation_id, "sceneId": scene_id, "revision": expected + 1,
                          "deletedAt": timestamp, "reasonCode": "scene_removed", "softDeleted": True}
                audit_change(session, context, request_id, "scene.remove", "scene", scene_id, before, after)
                if session is not None:
                    row = session.get(ProjectSceneRecord, (project_id, scene_id))
                    row.enabled, row.approved, row.revision = False, False, expected + 1
                    row.deleted_at, row.deletion_operation_id = now, operation_id
                    # Retain members, plans, and installations for audit; never cascade artifacts.
                    session.add(ResourceLifecycleOperationRecord(operation_id=operation_id, request_key=request_key,
                        scope_key=scope, actor_id=actor, request_digest=request_digest, stage="confirmed",
                        payload={"expectedRevision": expected}, result=result))
                    add_event(session, scope, expected + 1, result, operation_id)
                    for grant in session.scalars(select(ProjectSceneRuntimeGrantRecord).where(
                            ProjectSceneRuntimeGrantRecord.project_id == project_id,
                            ProjectSceneRuntimeGrantRecord.scene_id == scene_id,
                            ProjectSceneRuntimeGrantRecord.revoked_at.is_(None))):
                        grant.revoked_at = now
                else:
                    self._memory[(project_id, scene_id)] = after
                    self._removal_operations[request_key] = {"digest": request_digest, "result": result}
                return deepcopy(result)

    def member_profile(self, project_id, scene_id, member_id, revision):
        scene = self.visible(project_id, scene_id, manage=True)
        if scene["revision"] != revision:
            reject("revision_conflict", "scene revision was changed")
        member = next((m for m in scene["models"] if m["memberId"] == member_id), None)
        if member is None:
            reject("scene_member_not_found", "scene member not found", 404)
        profile = member.get("parameterSnapshot")
        if not profile:
            assignment = self.assignments.resolve(project_id, member["projectModelId"])
            if assignment is None:
                reject("project_model_not_found", "project model is not assigned", 404)
            profile = assignment["parameterSnapshot"]
        return {**deepcopy(profile), "sceneRevision": scene["revision"], "audit": []}

    def save_member_profile(self, project_id, scene_id, member_id, scene_revision, values, *,
                            expected_revision, actor, context, request_id=None):
        with self._lock, self.assignments.parameters._lock:
            current = self.member_profile(project_id, scene_id, member_id, scene_revision)
            if expected_revision != current["revision"]:
                reject("revision_conflict", "scene member parameters were changed")
            scene = self.get(project_id, scene_id)
            member = next(m for m in scene["models"] if m["memberId"] == member_id)
            assignment = self.assignments.resolve(project_id, member["projectModelId"])
            if assignment is None:
                reject("project_model_not_found", "project model is not assigned", 404)
            normalized = self.assignments.parameters._normalize_values(values)
            profile = {**current, **normalized, "revision": current["revision"] + 1,
                "source": "custom", "updatedAt": datetime.now(timezone.utc).isoformat(),
                "updatedBy": actor, "sceneId": scene_id, "memberId": member_id,
                "inventoryRevision": assignment["parameterRevision"]}
            for key in ("audit", "sceneRevision", "inheritedRevision"):
                profile.pop(key, None)
            self.assignments.parameters._validate_profile(self.catalog_model(member), profile)
            self.save(project_id, scene_id, {}, scene_revision, context=context, request_id=request_id,
                      member_profile_update=(member_id, profile))
            return self.member_profile(project_id, scene_id, member_id, scene_revision + 1)

    def save(self, project_id, scene_id, changes, expected, *, context=None, request_id=None, creating=False, approval_reason=None, member_profile_update=None):
        with self._lock, self.assignments.parameters._lock:
            # Legacy import may write: finish it before holding project row locks.
            if self.persistent:
                self.assignments.parameters._import_legacy_once()
            if self.persistent:
                with self.database.session() as session:
                    return self._save(session, project_id, scene_id, changes, expected, context, request_id, creating, approval_reason, member_profile_update)
            return self._save(None, project_id, scene_id, changes, expected, context, request_id, creating, approval_reason, member_profile_update)


def create_scene_router(provider):
    router = APIRouter(prefix="/aiyoloapi/projects/{project_id}/scenes", tags=["project scenes"])
    manage = require_project_capability(PROJECT_SCENES_MANAGE)
    read = require_project_capability(PROJECT_READ)

    @router.get("/{scene_id}/removal-impact")
    async def removal_impact(project_id: str, scene_id: str, context=Depends(manage)):
        return provider().removal_impact(project_id, scene_id)

    @router.delete("/{scene_id}")
    async def remove_scene(project_id: str, scene_id: str, request: Request, context=Depends(manage)):
        expected, key = deletion_headers(request)
        return provider().soft_delete(project_id, scene_id, expected, key, context=context,
            request_id=getattr(request.state, "request_id", None))

    @router.get("")
    async def list_scenes(project_id: str, target: Literal["pc", "mobile"] | None = None,
                          input_type: Literal["image", "video"] | None = Query(default=None, alias="inputType"),
                          context=Depends(read)):
        return {"projectId": project_id, "scenes": provider().list_catalog(project_id,
            manage=PROJECT_SCENES_MANAGE in context.capabilities, target=target, input_type=input_type)}

    @router.get("/{scene_id}")
    async def get_scene(project_id: str, scene_id: str, target: Literal["pc", "mobile"] | None = None,
                         input_type: Literal["image", "video"] | None = Query(default=None, alias="inputType"),
                         context=Depends(read)):
        return provider().visible(project_id, scene_id, manage=PROJECT_SCENES_MANAGE in context.capabilities,
                                  target=target, input_type=input_type)

    @router.post("", status_code=201)
    async def create_scene(project_id: str, body: SceneCreate, request: Request, context=Depends(manage)):
        changes = body.model_dump(exclude={"expectedRevision", "sceneId"})
        changes["models"] = ordered_members(body.models)
        return provider().save(project_id, body.sceneId, changes, body.expectedRevision, context=context,
            request_id=request.headers.get("x-request-id", "")[:128] or None, creating=True)

    @router.patch("/{scene_id}")
    async def patch_scene(project_id: str, scene_id: str, body: ScenePatch, request: Request, context=Depends(manage)):
        return provider().save(project_id, scene_id, body.model_dump(exclude={"expectedRevision"}, exclude_unset=True),
            body.expectedRevision, context=context, request_id=request.headers.get("x-request-id", "")[:128] or None)

    @router.put("/{scene_id}/models")
    async def set_models(project_id: str, scene_id: str, body: SceneModels, request: Request, context=Depends(manage)):
        return provider().save(project_id, scene_id, {"models": ordered_members(body.models)}, body.expectedRevision,
            context=context, request_id=request.headers.get("x-request-id", "")[:128] or None)

    @router.put("/{scene_id}/plans")
    async def set_plans(project_id: str, scene_id: str, body: ScenePlans, request: Request, context=Depends(manage)):
        return provider().save(project_id, scene_id, {"plans": [plan.model_dump() for plan in body.plans]},
            body.expectedRevision, context=context, request_id=request.headers.get("x-request-id", "")[:128] or None)

    @router.get("/{scene_id}/plans/{plan_id}")
    async def get_plan(project_id: str, scene_id: str, plan_id: str, target: Literal["pc", "mobile"] | None = None,
                       input_type: Literal["image", "video"] | None = Query(default=None, alias="inputType"),
                       context=Depends(read)):
        scene = provider().visible(project_id, scene_id, manage=PROJECT_SCENES_MANAGE in context.capabilities,
                                   target=target, input_type=input_type)
        plan = next((item for item in scene.get("plans", []) if item["planId"] == plan_id), None)
        if plan is None:
            reject("plan_not_found", "plan not found", 404)
        return {"projectId": project_id, "sceneId": scene_id, "revision": scene["revision"], **plan}

    @router.get("/{scene_id}/installation")
    async def get_installation(project_id: str, scene_id: str, target: Literal["pc", "mobile"],
                               plan_id: str | None = Query(default=None, alias="planId"),
                               member_ids: list[str] | None = Query(default=None, alias="memberId"),
                               context=Depends(read)):
        return provider().installation(project_id, scene_id, context.principal.account_id, target,
                                       plan_id=plan_id, member_ids=member_ids)

    @router.post("/{scene_id}/installation/prepare")
    async def prepare_installation(project_id: str, scene_id: str, body: SceneInstallationRequest,
                                   request: Request,
                                   context=Depends(require_project_capability(PROJECT_INSPECTION_USE))):
        return provider().prepare_installation(project_id, scene_id, context.principal.account_id,
                                                body.target, body.expectedRevision,
                                                plan_id=body.planId, member_ids=body.memberIds,
                                                context=context,
                                                request_id=request.headers.get("x-request-id", "")[:128] or None)

    @router.post("/{scene_id}/approval")
    async def approve_scene(project_id: str, scene_id: str, body: SceneApproval, request: Request,
                             context=Depends(require_project_capability(PROJECT_SCENES_APPROVE))):
        return provider().save(project_id, scene_id, {"approved": body.approved}, body.expectedRevision,
            context=context, request_id=request.headers.get("x-request-id", "")[:128] or None, approval_reason=body.reason)

    @router.get("/{scene_id}/models/{model_id}/versions/{version}/artifacts/{artifact_id}/download")
    async def download_scene_artifact(project_id: str, scene_id: str, model_id: str, version: str,
                                        artifact_id: str, request: Request,
                                        expected_revision: int | None = Query(default=None, ge=1, alias="expectedRevision"),
                                        context=Depends(read)):
        artifact, path = provider().artifact(project_id, scene_id, model_id, version, artifact_id, expected_revision)
        from .model_updates.download import artifact_response
        from .main import _acquire_model_download, _release_model_download
        from .config import settings
        return artifact_response(request, artifact, path, acquire=_acquire_model_download,
            release=_release_model_download, chunk_size=int(settings.model_download_chunk_size))

    @router.get("/{scene_id}/models/{model_id}/versions/{version}/parameters")
    async def scene_parameters(project_id: str, scene_id: str, model_id: str, version: str,
                               target: Literal["pc", "mobile"],
                               expected_revision: int = Query(ge=1, alias="expectedRevision"), context=Depends(read)):
        return provider().parameters(project_id, scene_id, model_id, version, target, expected_revision)

    @router.post("/{scene_id}/resolve")
    async def resolve_scene(project_id: str, scene_id: str, body: SceneResolution,
                              context=Depends(require_project_capability(PROJECT_INSPECTION_USE))):
        store = provider()
        scene = store.visible(project_id, scene_id, target=body.target)
        if scene["revision"] != body.expectedRevision:
            reject("revision_conflict", "scene revision was changed")
        if body.inputType not in scene["inputTypes"]:
            reject("scene_input_not_supported", "scene does not support input type")
        if not scene["executionSupported"]:
            reject("execution_mode_not_supported", "multi-model sync/async execution is not implemented")
        if not scene["models"][0]["executionReady"]:
            reject("scene_parameters_not_approved", "scene needs parameter review before execution")
        return {"projectId": project_id, "sceneId": scene_id, "revision": scene["revision"],
                "model": scene["models"][0], "inputType": body.inputType, "resolutionOnly": True}

    @router.post("/{scene_id}/plans/{plan_id}/resolve")
    async def resolve_plan(project_id: str, scene_id: str, plan_id: str, body: ScenePlanResolution,
                           context=Depends(require_project_capability(PROJECT_INSPECTION_USE))):
        if body.planId != plan_id:
            reject("invalid_scene_suite", "planId does not match path", 422)
        return provider().resolve_plan(project_id, scene_id, plan_id, body)

    @router.post("/{scene_id}/plans/{plan_id}/runtime-grants")
    async def manage_runtime_grant(project_id: str, scene_id: str, plan_id: str,
                                   body: SceneRuntimeGrantRequest, request: Request,
                                   context=Depends(require_project_capability(PROJECT_INSPECTION_USE))):
        if body.planId != plan_id:
            reject("invalid_scene_suite", "planId does not match path", 422)
        return provider().runtime_grant(project_id, scene_id, plan_id,
            context.principal.account_id, body, context=context,
            request_id=request.headers.get("x-request-id", "")[:128] or None,
            idempotency_key=request.headers.get("idempotency-key", "")[:128] or None)

    return router
