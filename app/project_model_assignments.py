"""Project-scoped approval of published model releases and parameter snapshots."""
from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timezone
from threading import RLock

from fastapi import HTTPException
from sqlalchemy import select

from .database import (DEFAULT_PROJECT_ID, ModelParameterProfileRecord, ProjectModelAssignmentRecord,
                       ProjectSceneMemberRecord, ProjectRecord, StreamConfigRecord,
                       AccountRecord, ProjectMembershipRecord)
from .project_business import _memory_model_assignments, audit_change, lock_project
from .resource_lifecycle import guard_model_write


class AssignmentConflict(ValueError):
    pass


_assignment_lock = RLock()




class ProjectModelAssignments:
    """Project-level inventory of exact model releases and target deployments."""

    def __init__(self, database_manager, catalog, parameter_store, stream_store=None):
        self.database = database_manager
        self.catalog = catalog
        self.parameters = parameter_store
        self.stream_store = stream_store
        self._lock = _assignment_lock

    def project_active(self, project_id):
        if self.database is not None and self.database.enabled:
            with self.database.session() as session:
                row = session.get(ProjectRecord, project_id)
                return row is not None and row.lifecycle_state == "ACTIVE"
        from .project_auth import memory_project_lifecycle
        return memory_project_lifecycle(project_id) == "ACTIVE"

    @staticmethod
    def _platform(target):
        if target in {"pc", "server"}:
            return "server"
        if target in {"mobile", "android"}:
            return "android"
        raise HTTPException(422, detail={"code": "invalid_target", "message": "target must be pc or mobile"})

    @classmethod
    def _target(cls, platform):
        return "pc" if cls._platform(platform) == "server" else "mobile"

    @classmethod
    def _public(cls, row):
        if isinstance(row, dict):
            value = {key: deepcopy(item) for key, item in row.items()
                     if key != "parameterSnapshot"}
            platform = value.get("parameterPlatform", value.get("platform", "server"))
            value["parameterPlatform"] = cls._platform(platform)
            value["target"] = cls._target(platform)
            value["projectModelId"] = value.get("projectModelId", value.get("assignmentId"))
            value["assignmentId"] = value["projectModelId"]
            return value
        return {
            "projectModelId": row.assignment_id, "assignmentId": row.assignment_id,
            "projectId": row.project_id, "modelId": row.model_id,
            "modelVersion": row.model_version, "target": cls._target(row.parameter_platform),
            "parameterPlatform": row.parameter_platform,
            "parameterRevision": row.parameter_revision,
            "parameterProfileKey": row.parameter_profile_key,
            "enabled": row.enabled, "revision": row.revision,
        }

    @staticmethod
    def _memory_key(project_id, model_id, version, platform):
        return (project_id, model_id, version, ProjectModelAssignments._platform(platform))

    def list(self, project_id, target=None):
        platform = self._platform(target) if target is not None else None
        if self.database is not None and self.database.enabled:
            with self.database.session() as session:
                query = select(ProjectModelAssignmentRecord).where(
                    ProjectModelAssignmentRecord.project_id == project_id)
                if platform is not None:
                    query = query.where(ProjectModelAssignmentRecord.parameter_platform == platform)
                rows = session.scalars(query.order_by(
                    ProjectModelAssignmentRecord.model_id,
                    ProjectModelAssignmentRecord.model_version,
                    ProjectModelAssignmentRecord.parameter_platform)).all()
                return [self._display(row) for row in rows]
        with self._lock:
            rows = [self._display(row) for key, row in sorted(_memory_model_assignments.items())
                    if key[0] == project_id and (platform is None or self._platform(row.get("parameterPlatform", "server")) == platform)]
        return rows

    def _display(self, row):
        from .model_display import catalog_model_name
        value = self._public(row)
        value["modelName"] = catalog_model_name(self.catalog, value["modelId"], value["modelVersion"])
        return value

    def get(self, project_id, project_model_id):
        if self.database is not None and self.database.enabled:
            with self.database.session() as session:
                row = session.get(ProjectModelAssignmentRecord, project_model_id)
                return self._display(row) if row is not None and row.project_id == project_id else None
        with self._lock:
            row = next((item for item in _memory_model_assignments.values()
                        if item.get("projectId") == project_id
                        and item.get("projectModelId", item.get("assignmentId")) == project_model_id), None)
            return self._display(row) if row is not None else None

    def resolve(self, project_id, project_model_id, *, session=None, lock=False, enabled_only=True):
        """Resolve one inventory item, including its frozen parameter snapshot.

        Scene writes pass their existing transaction so the inventory authorization
        and scene revision are checked under the same project lock.
        """
        if self.database is not None and self.database.enabled:
            if session is None:
                with self.database.session() as owned_session:
                    return self.resolve(project_id, project_model_id, session=owned_session,
                                        lock=lock, enabled_only=enabled_only)
            query = select(ProjectModelAssignmentRecord).where(
                ProjectModelAssignmentRecord.assignment_id == project_model_id,
                ProjectModelAssignmentRecord.project_id == project_id,
            )
            if lock:
                query = query.with_for_update()
            row = session.scalar(query)
            if row is None or enabled_only and not row.enabled:
                return None
            return {**self._public(row), "parameterSnapshot": deepcopy(row.parameter_snapshot)}
        with self._lock:
            row = next((item for item in _memory_model_assignments.values()
                        if item.get("projectId") == project_id
                        and item.get("projectModelId", item.get("assignmentId")) == project_model_id), None)
            if row is None or enabled_only and not row.get("enabled"):
                return None
            return {**self._public(row), "parameterSnapshot": deepcopy(row.get("parameterSnapshot"))}

    def assigned(self, project_id, model_id, version=None, *, active_only=True):
        return [row for row in self.list(project_id)
                if row["modelId"] == model_id and (version is None or row["modelVersion"] == version)
                and (not active_only or row["enabled"])]

    def references(self, model_id, version=None):
        if self.database is not None and self.database.enabled:
            with self.database.session() as session:
                query = select(ProjectModelAssignmentRecord).where(
                    ProjectModelAssignmentRecord.model_id == model_id,
                    ProjectModelAssignmentRecord.enabled.is_(True))
                if version is not None:
                    query = query.where(ProjectModelAssignmentRecord.model_version == version)
                return [self._public(row) for row in session.scalars(query).all()]
        with self._lock:
            return [self._public(row) for row in _memory_model_assignments.values()
                    if row.get("enabled") and row.get("modelId") == model_id
                    and (version is None or row.get("modelVersion") == version)]

    def snapshot(self, project_id, model_id, version=None, platform=None):
        target_platform = self._platform(platform) if platform is not None else None
        for assignment in self.assigned(project_id, model_id, version):
            if target_platform is not None and assignment["parameterPlatform"] != target_platform:
                continue
            if self.database is not None and self.database.enabled:
                with self.database.session() as session:
                    row = session.get(ProjectModelAssignmentRecord, assignment["projectModelId"])
                    if (row is not None and row.enabled and row.parameter_snapshot
                            and row.model_id == model_id and row.model_version == assignment["modelVersion"]
                            and (target_platform is None or row.parameter_platform == target_platform)):
                        return deepcopy(row.parameter_snapshot)
            else:
                with self._lock:
                    row = _memory_model_assignments.get(self._memory_key(
                        project_id, model_id, assignment["modelVersion"], assignment["parameterPlatform"]))
                    if row and row.get("enabled") and row.get("parameterSnapshot"):
                        return deepcopy(row["parameterSnapshot"])
        return None

    def _validate_model(self, model_id, version, platform):
        try:
            model = self.catalog.get(model_id, version)
        except KeyError as exc:
            raise HTTPException(404, detail={"code": "model_not_found", "message": "model release not found"}) from exc
        if model.get("status") != "PUBLISHED" or not model.get("releaseEligible"):
            raise HTTPException(409, detail={"code": "model_not_published", "message": "only published releases may be assigned"})
        target = self._target(platform)
        if target not in model.get("supportedTargets", []):
            raise HTTPException(409, detail={"code": "model_target_not_supported", "message": f"model release does not support {target}"})
        ready = model.get("serverReady") if platform == "server" else model.get("androidReady")
        if not ready or not model.get("targetReadiness", {}).get(target, {}).get("ready"):
            raise HTTPException(409, detail={"code": "model_target_not_ready", "message": f"model target is not ready: {target}"})
        if not model.get("targetReleaseEligible", {}).get(target, False):
            raise HTTPException(409, detail={"code": "model_target_not_published", "message": f"{target} release is not approved"})
        return model

    def save(self, project_id, model_id, version, target, parameter_revision, enabled,
             expected_revision, *, context=None, request_id=None,
             audit_action="project_model.assign", audit_reason=None, _session=None, _audit=True):
        platform = self._platform(target)
        model = self._validate_model(model_id, version, platform)
        with self._lock, self.parameters._lock:
            profile = self.parameters.get(model, platform, project_id)
            if profile["revision"] != parameter_revision:
                raise AssignmentConflict("parameter revision was changed")
            # Keep the consumable profile contract in the frozen assignment. Scenes
            # copy this exact snapshot at approval; they must not reconstruct metadata
            # from whichever project/global profile happens to be current later.
            snapshot = {key: deepcopy(profile[key]) for key in
                        ("schemaVersion", "source", "updatedAt", "detection", "alertRules")}
            snapshot.update(projectId=project_id, modelId=model_id, modelVersion=version, platform=platform,
                            revision=parameter_revision, inheritedRevision=profile.get("inheritedRevision"))
            if self.database is not None and self.database.enabled:
                with (nullcontext(_session) if _session is not None else self.database.session()) as session:
                    lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
                    lock_project(session, project_id)
                    self._check_write_authority(session, project_id, context)
                    guard_model_write(session, self.catalog, model_id, version)
                    if self.catalog.get(model_id, version) != model:
                        raise AssignmentConflict("model release changed before assignment; refresh selection")
                    row = session.scalar(select(ProjectModelAssignmentRecord).where(
                        ProjectModelAssignmentRecord.project_id == project_id,
                        ProjectModelAssignmentRecord.model_id == model_id,
                        ProjectModelAssignmentRecord.model_version == version,
                        ProjectModelAssignmentRecord.parameter_platform == platform).with_for_update())
                    before = self._public(row) if row else None
                    if expected_revision != (row.revision if row else 0):
                        raise AssignmentConflict("project model was changed")
                    if row is not None and (row.parameter_revision != parameter_revision
                            or row.parameter_snapshot != snapshot or not enabled) and platform == "server":
                        bound = session.scalar(select(StreamConfigRecord.stream_id).where(
                            StreamConfigRecord.project_id == project_id,
                            StreamConfigRecord.model_id == model_id,
                            StreamConfigRecord.model_version == version,
                            StreamConfigRecord.enabled.is_(True)).limit(1))
                        if bound is not None:
                            raise AssignmentConflict("project model is used by an active stream")
                    key = self.parameters._database_key_for_model(model, platform, project_id)
                    stored = session.get(ModelParameterProfileRecord, (project_id, key))
                    if (stored.revision if stored else 0) != parameter_revision:
                        raise AssignmentConflict("parameter revision was changed")
                    if profile.get("source") == "inherited":
                        inherited_key = self.parameters._database_key_for_model(model, platform)
                        inherited = session.get(ModelParameterProfileRecord, (DEFAULT_PROJECT_ID, inherited_key))
                        if (inherited.revision if inherited else 0) != profile.get("inheritedRevision", 0):
                            raise AssignmentConflict("inherited parameter revision was changed")
                    if stored is None:
                        key = None
                    if row is None:
                        row = ProjectModelAssignmentRecord(
                            project_id=project_id, model_id=model_id, model_version=version,
                            created_at=datetime.now(timezone.utc),
                            created_by_account_id=context.principal.account_id if context else None)
                        session.add(row)
                    row.parameter_platform, row.parameter_revision = platform, parameter_revision
                    row.parameter_profile_key, row.parameter_snapshot = key, snapshot
                    row.enabled, row.revision = enabled, expected_revision + 1
                    row.updated_at = datetime.now(timezone.utc)
                    session.flush()
                    after = self._public(row)
                    from .model_updates.events import add_domain_event
                    add_domain_event(session, project_id, "assignment", after)
                    if audit_reason:
                        after = {**after, "reason": audit_reason.strip()[:512]}
                    if _audit:
                        audit_change(session, context, request_id, audit_action,
                                     "project_model", after["projectModelId"], before, after)
                    return after
            self._check_write_authority(None, project_id, context)
            guard_model_write(None, self.catalog, model_id, version)
            if self.catalog.get(model_id, version) != model:
                raise AssignmentConflict("model release changed before assignment; refresh selection")
            latest_profile = self.parameters.get(model, platform, project_id)
            if latest_profile.get("revision") != parameter_revision:
                raise AssignmentConflict("parameter revision was changed")
            snapshot = {key: deepcopy(latest_profile[key]) for key in
                        ("schemaVersion", "source", "updatedAt", "detection", "alertRules")}
            snapshot.update(projectId=project_id, modelId=model_id, modelVersion=version, platform=platform,
                            revision=parameter_revision, inheritedRevision=latest_profile.get("inheritedRevision"))
            memory_key = self._memory_key(project_id, model_id, version, platform)
            existing = _memory_model_assignments.get(memory_key)
            before = self._public(existing) if existing else None
            if expected_revision != (existing.get("revision", 0) if existing else 0):
                raise AssignmentConflict("project model was changed")
            if existing and platform == "server" and (not enabled or existing.get("parameterSnapshot") != snapshot):
                if self.stream_store is not None and any(
                        item.enabled and item.model_id == model_id and item.model_version == version
                        for item in self.stream_store.list(project_id)):
                    raise AssignmentConflict("project model is used by an active stream")
            from uuid import uuid4
            after = {"projectModelId": existing.get("projectModelId", existing.get("assignmentId")) if existing else str(uuid4()),
                     "assignmentId": existing.get("assignmentId", existing.get("projectModelId")) if existing else None,
                     "projectId": project_id, "modelId": model_id, "modelVersion": version,
                     "parameterPlatform": platform, "target": self._target(platform),
                     "parameterRevision": parameter_revision, "parameterProfileKey": None,
                     "parameterSnapshot": snapshot, "enabled": enabled, "revision": expected_revision + 1}
            after["assignmentId"] = after["assignmentId"] or after["projectModelId"]
            _memory_model_assignments[memory_key] = deepcopy(after)
            public_after = self._public(after)
            if audit_reason:
                public_after = {**public_after, "reason": audit_reason.strip()[:512]}
            if _audit:
                audit_change(None, context, request_id, audit_action,
                             "project_model", public_after["projectModelId"], before, public_after)
            return public_after

    def remove(self, project_id, project_model_id, expected_revision, *, context=None, request_id=None):
        with self._lock:
            if self.database is not None and self.database.enabled:
                with self.database.session() as session:
                    lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
                    lock_project(session, project_id)
                    self._check_write_authority(session, project_id, context)
                    row = session.scalar(select(ProjectModelAssignmentRecord).where(
                        ProjectModelAssignmentRecord.assignment_id == project_model_id,
                        ProjectModelAssignmentRecord.project_id == project_id).with_for_update())
                    if row is None:
                        raise HTTPException(404, detail={"code": "project_model_not_found", "message": "project model not found"})
                    before = self._public(row)
                    if row.revision != expected_revision:
                        raise AssignmentConflict("project model was changed")
                    referenced = session.scalar(select(ProjectSceneMemberRecord.member_id).where(
                        ProjectSceneMemberRecord.project_model_id == project_model_id).limit(1))
                    if referenced is not None:
                        raise AssignmentConflict("project model is referenced by a project scene")
                    if row.parameter_platform == "server":
                        bound = session.scalar(select(StreamConfigRecord.stream_id).where(
                            StreamConfigRecord.project_id == project_id,
                            StreamConfigRecord.model_id == row.model_id,
                            StreamConfigRecord.model_version == row.model_version,
                            StreamConfigRecord.enabled.is_(True)).limit(1))
                        if bound is not None:
                            raise AssignmentConflict("project model is used by an active stream")
                    session.delete(row)
                    session.flush()
                    audit_change(session, context, request_id, "project_model.remove",
                                 "project_model", project_model_id, before, None)
                    return {"projectModelId": project_model_id, "removed": True}
            self._check_write_authority(None, project_id, context)
            row = next((item for item in _memory_model_assignments.values()
                        if item.get("projectId") == project_id
                        and item.get("projectModelId", item.get("assignmentId")) == project_model_id), None)
            if row is None:
                raise HTTPException(404, detail={"code": "project_model_not_found", "message": "project model not found"})
            before = self._public(row)
            if row.get("revision") != expected_revision:
                raise AssignmentConflict("project model was changed")
            try:
                from .main import project_scenes
                if any(member.get("projectModelId") == project_model_id
                       for scene in project_scenes.list(project_id) for member in scene.get("models", [])):
                    raise AssignmentConflict("project model is referenced by a project scene")
            except ImportError:
                pass
            if row.get("parameterPlatform") == "server" and self.stream_store is not None and any(
                    item.enabled and item.model_id == row["modelId"] and item.model_version == row["modelVersion"]
                    for item in self.stream_store.list(project_id)):
                raise AssignmentConflict("project model is used by an active stream")
            key = self._memory_key(project_id, row["modelId"], row["modelVersion"], row["parameterPlatform"])
            _memory_model_assignments.pop(key, None)
            audit_change(None, context, request_id, "project_model.remove", "project_model", project_model_id, before, None)
            return {"projectModelId": project_model_id, "removed": True}

    def _check_write_authority(self, session, project_id, context):
        project = session.get(ProjectRecord, project_id) if session is not None else None
        active = project is not None and project.lifecycle_state == "ACTIVE" if session is not None else self.project_active(project_id)
        if not active:
            raise HTTPException(403, detail={"code": "project_inactive", "message": "project is not active"})
        if context is None:
            return
        if session is not None:
            account = session.get(AccountRecord, context.principal.account_id)
            member = session.get(ProjectMembershipRecord, (project_id, context.principal.account_id))
            if account is not None and account.enabled and (account.platform_role == "PLATFORM_ADMIN" or
                    member is not None and member.enabled and member.project_role == "PROJECT_OWNER"):
                return
        else:
            from .project_auth import PROJECT_MODELS_ASSIGN, resolve_project_context
            if PROJECT_MODELS_ASSIGN in resolve_project_context(context.principal, project_id).capabilities:
                return
        raise HTTPException(403, detail={"code": "capability_required", "message": "model assignment authority was revoked"})
