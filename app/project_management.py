from __future__ import annotations

import re
import base64
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, or_, and_, tuple_
from sqlalchemy.exc import IntegrityError

from . import auth
from .audit_query import audit_filters
from .database import (
    AccountRecord,
    PlatformAuditEventRecord,
    ProjectAuditEventRecord,
    ProjectMembershipRecord,
    ProjectRecord,
)
from .project_auth import (
    NORMAL_USER,
    PLATFORM_ACCOUNTS_MANAGE,
    PLATFORM_ADMIN,
    PLATFORM_AUDIT_READ,
    PLATFORM_PROJECTS_MANAGE,
    PROJECT_ACTIVE,
    PROJECT_AUDIT_READ,
    PROJECT_ARCHIVED,
    PROJECT_MEMBERS_MANAGE,
    PROJECT_OWNER,
    PROJECT_OWNER_CAPABILITIES,
    PROJECT_SUSPENDED,
    PROJECT_USER,
    PROJECT_USER_CAPABILITIES,
    ProjectContext,
    _lifecycle_capabilities,
    remove_memory_membership,
    require_platform_capability,
    require_principal,
    require_project_capability,
    set_memory_membership,
    set_memory_project,
)


PROJECT_CODE = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")
PROJECT_ROLES = {PROJECT_OWNER, PROJECT_USER}


class ProjectCreateRequest(BaseModel):
    projectCode: str = Field(min_length=3, max_length=64)
    displayName: str = Field(min_length=1, max_length=255)
    ownerAccountId: str = Field(min_length=1, max_length=36)


class ProjectPatchRequest(BaseModel):
    expectedRevision: int = Field(ge=1)
    projectCode: str | None = Field(default=None, min_length=3, max_length=64)
    displayName: str | None = Field(default=None, min_length=1, max_length=255)


class RevisionRequest(BaseModel):
    expectedRevision: int = Field(ge=1)


class AccountCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    platformRole: str = Field(default=NORMAL_USER, pattern="^(PLATFORM_ADMIN|NORMAL_USER)$")


class AccountPatchRequest(BaseModel):
    expectedRevision: int = Field(ge=1)
    enabled: bool | None = None
    platformRole: str | None = Field(default=None, pattern="^(PLATFORM_ADMIN|NORMAL_USER)$")


class MembershipCreateRequest(BaseModel):
    accountId: str = Field(min_length=1, max_length=36)
    projectRole: str = Field(default=PROJECT_USER, pattern="^(PROJECT_OWNER|PROJECT_USER)$")


class MembershipPatchRequest(BaseModel):
    expectedRevision: int = Field(ge=1)
    enabled: bool | None = None
    projectRole: str | None = Field(default=None, pattern="^(PROJECT_OWNER|PROJECT_USER)$")


class OwnerTransferRequest(BaseModel):
    fromAccountId: str = Field(min_length=1, max_length=36)
    toAccountId: str = Field(min_length=1, max_length=36)
    expectedFromRevision: int = Field(ge=1)
    expectedToRevision: int = Field(ge=1)


@dataclass(frozen=True)
class _MemoryProjectData:
    project_id: str
    project_code: str
    display_name: str
    lifecycle_state: str
    revision: int
    created_by_account_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class _MemoryMembershipData:
    project_id: str
    account_id: str
    project_role: str
    enabled: bool
    revision: int
    created_by_account_id: str
    created_at: datetime
    updated_at: datetime


_mutation_lock = RLock()
_memory_projects: dict[str, _MemoryProjectData] = {}
_memory_memberships: dict[tuple[str, str], _MemoryMembershipData] = {}
_memory_project_audits: list[dict] = []
_memory_platform_audits: list[dict] = []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "").strip()
    return supplied[:128] if supplied else str(uuid4())


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _conflict(code: str, message: str) -> HTTPException:
    return _error(status.HTTP_409_CONFLICT, code, message)


def _forbidden(code: str, message: str) -> HTTPException:
    return _error(status.HTTP_403_FORBIDDEN, code, message)


def _not_found(resource: str) -> HTTPException:
    return _error(status.HTTP_404_NOT_FOUND, f"{resource}_not_found", f"{resource} was not found")


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _normalise_project_code(value: str) -> str:
    code = value.strip().lower()
    if not PROJECT_CODE.fullmatch(code):
        raise _error(422, "project_code_invalid", "projectCode must use lowercase letters, digits and hyphens")
    return code


def _fingerprint(payload: dict) -> str:
    canonical = "|".join(f"{key}={payload[key]}" for key in sorted(payload))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _project_payload(project) -> dict:
    return {
        "projectId": project.project_id,
        "projectCode": project.project_code,
        "displayName": project.display_name,
        "lifecycleState": project.lifecycle_state,
        "revision": project.revision,
        "createdByAccountId": project.created_by_account_id,
        "createdAt": _timestamp(project.created_at),
        "updatedAt": _timestamp(project.updated_at),
    }


def _account_payload(account) -> dict:
    return {
        "accountId": account.account_id,
        "username": account.username,
        "platformRole": account.platform_role,
        "enabled": account.enabled,
        "revision": account.revision,
        "createdAt": _timestamp(getattr(account, "created_at", None)),
        "updatedAt": _timestamp(getattr(account, "updated_at", None)),
    }


def _membership_payload(membership, account=None) -> dict:
    payload = {
        "projectId": membership.project_id,
        "accountId": membership.account_id,
        "projectRole": membership.project_role,
        "enabled": membership.enabled,
        "revision": membership.revision,
        "createdByAccountId": membership.created_by_account_id,
        "createdAt": _timestamp(membership.created_at),
        "updatedAt": _timestamp(membership.updated_at),
    }
    if account is not None:
        payload.update({"username": account.username, "accountEnabled": account.enabled})
    return payload


def _capabilities(project_role: str, lifecycle_state: str) -> list[str]:
    values = PROJECT_OWNER_CAPABILITIES if project_role == PROJECT_OWNER else PROJECT_USER_CAPABILITIES
    if lifecycle_state == PROJECT_ACTIVE:
        return sorted(values)
    if lifecycle_state == PROJECT_SUSPENDED:
        return sorted(values.intersection({
            "project.read", "project.alerts.read", "project.audit.read",
            "project.alert_knowledge.read", "project.alert_advice.read",
            "project.alert_advice.history.read", "project.members.manage",
            "project.settings.manage", "project.service_principals.manage",
        }))
    if project_role == PROJECT_OWNER:
        return sorted(values.intersection({
            "project.read", "project.alerts.read", "project.audit.read",
            "project.alert_knowledge.read", "project.alert_advice.read",
            "project.alert_advice.history.read",
        }))
    return []


def _add_project_audit(
    session,
    context,
    request_id: str,
    action: str,
    target_type: str,
    target_id: str,
    previous_revision: int | None,
    new_revision: int | None,
    changes: dict,
) -> None:
    record = {
        "auditId": str(uuid4()),
        "occurredAt": _timestamp(_now()),
        "requestId": request_id,
        "actorAccountId": context.principal.account_id,
        "actorServicePrincipalId": getattr(context.principal, "service_principal_id", None),
        "platformRole": context.principal.platform_role,
        "projectId": context.project_id,
        "projectRole": context.project_role,
        "action": action,
        "targetType": target_type,
        "targetId": target_id,
        "previousRevision": previous_revision,
        "newRevision": new_revision,
        "changeSummary": changes,
        "outcome": "SUCCESS",
        "failureCode": None,
    }
    if session is None:
        _memory_project_audits.append(record)
        return
    session.add(ProjectAuditEventRecord(
        audit_id=record["auditId"], request_id=request_id,
        actor_account_id=context.principal.account_id, platform_role=context.principal.platform_role,
        actor_service_principal_id=getattr(context.principal, "service_principal_id", None),
        project_id=context.project_id, project_role=context.project_role, action=action,
        target_type=target_type, target_id=target_id, previous_revision=previous_revision,
        new_revision=new_revision, change_summary=changes, outcome="SUCCESS",
    ))
    if action.startswith(('membership.', 'project.')):
        from .model_updates.events import add_domain_event
        add_domain_event(session, context.project_id, action, {'targetId': target_id, 'revision': new_revision})


def _add_platform_audit(
    session,
    principal,
    request_id: str,
    action: str,
    target_type: str,
    target_id: str,
    previous_revision: int | None,
    new_revision: int | None,
    changes: dict,
) -> None:
    record = {
        "auditId": str(uuid4()), "occurredAt": _timestamp(_now()), "requestId": request_id,
        "actorAccountId": principal.account_id, "platformRole": principal.platform_role,
        "action": action, "targetType": target_type, "targetId": target_id,
        "previousRevision": previous_revision, "newRevision": new_revision,
        "changeSummary": changes, "outcome": "SUCCESS", "failureCode": None,
    }
    if session is None:
        _memory_platform_audits.append(record)
        return
    session.add(PlatformAuditEventRecord(
        audit_id=record["auditId"], request_id=request_id,
        actor_account_id=principal.account_id, platform_role=principal.platform_role,
        action=action, target_type=target_type, target_id=target_id,
        previous_revision=previous_revision, new_revision=new_revision,
        change_summary=changes, outcome="SUCCESS",
    ))


def _failure_code(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict):
        return str(exc.detail.get("code") or "write_denied")[:128]
    return "write_denied"


def _record_platform_denial(principal, request_id: str, action: str,
                            target_type: str, target_id: str, exc: HTTPException) -> None:
    record = {
        "auditId": str(uuid4()), "occurredAt": _timestamp(_now()), "requestId": request_id,
        "actorAccountId": principal.account_id, "platformRole": principal.platform_role,
        "action": action, "targetType": target_type, "targetId": target_id,
        "previousRevision": None, "newRevision": None, "changeSummary": {},
        "outcome": "DENIED", "failureCode": _failure_code(exc),
    }
    if not auth.database.enabled:
        _memory_platform_audits.append(record)
        return
    with auth.database.session() as session:
        session.add(PlatformAuditEventRecord(
            audit_id=record["auditId"], request_id=request_id,
            actor_account_id=principal.account_id, platform_role=principal.platform_role,
            action=action, target_type=target_type, target_id=target_id,
            change_summary={}, outcome="DENIED", failure_code=record["failureCode"],
        ))


def _record_project_denial(context: ProjectContext, request_id: str, action: str,
                           target_type: str, target_id: str, exc: HTTPException) -> None:
    record = {
        "auditId": str(uuid4()), "occurredAt": _timestamp(_now()), "requestId": request_id,
        "actorAccountId": context.principal.account_id, "platformRole": context.principal.platform_role,
        "actorServicePrincipalId": getattr(context.principal, "service_principal_id", None),
        "projectId": context.project_id, "projectRole": context.project_role,
        "action": action, "targetType": target_type, "targetId": target_id,
        "previousRevision": None, "newRevision": None, "changeSummary": {},
        "outcome": "DENIED", "failureCode": _failure_code(exc),
    }
    if not auth.database.enabled:
        _memory_project_audits.append(record)
        return
    with auth.database.session() as session:
        session.add(ProjectAuditEventRecord(
            audit_id=record["auditId"], request_id=request_id,
            actor_account_id=context.principal.account_id, platform_role=context.principal.platform_role,
            actor_service_principal_id=getattr(context.principal, "service_principal_id", None),
            project_id=context.project_id, project_role=context.project_role, action=action,
            target_type=target_type, target_id=target_id, change_summary={}, outcome="DENIED",
            failure_code=record["failureCode"],
        ))


def _platform_write(principal, request_id: str, action: str, target_type: str,
                    target_id: str, operation):
    try:
        return operation()
    except HTTPException as exc:
        _record_platform_denial(principal, request_id, action, target_type, target_id, exc)
        raise


def _project_write(context: ProjectContext, request_id: str, action: str,
                   target_type: str, target_id: str, operation):
    try:
        return operation()
    except HTTPException as exc:
        _record_project_denial(context, request_id, action, target_type, target_id, exc)
        raise


def _memory_account(account_id: str):
    return next((item for item in auth.memory_accounts_snapshot() if item.account_id == account_id), None)


def _project_context_for_platform(principal, project_id: str, project_role: str | None = None):
    return type("AuditContext", (), {
        "principal": principal, "project_id": project_id, "project_role": project_role,
    })()


def _assert_project_role_assignment(context: ProjectContext, project_role: str) -> None:
    if project_role not in PROJECT_ROLES:
        raise _error(422, "project_role_invalid", "project role is invalid")
    if not context.platform_entry and project_role == PROJECT_OWNER:
        raise _forbidden("project_role_escalation_forbidden", "project owners cannot grant PROJECT_OWNER")


def _assert_not_last_platform_admin(accounts, target, *, enabled: bool, platform_role: str) -> None:
    if target.enabled and target.platform_role == PLATFORM_ADMIN and (not enabled or platform_role != PLATFORM_ADMIN):
        others = [
            item for item in accounts
            if item.account_id != target.account_id and item.enabled and item.platform_role == PLATFORM_ADMIN
        ]
        if not others:
            raise _conflict("last_platform_admin", "the last enabled platform administrator cannot be disabled or demoted")


def _db_assert_account_not_last_owner(session, account_id: str) -> None:
    owned_projects = session.scalars(select(ProjectMembershipRecord.project_id).where(
        ProjectMembershipRecord.account_id == account_id,
        ProjectMembershipRecord.project_role == PROJECT_OWNER,
        ProjectMembershipRecord.enabled.is_(True),
    )).all()
    for project_id in owned_projects:
        other_count = session.scalar(
            select(func.count()).select_from(ProjectMembershipRecord).join(
                AccountRecord, AccountRecord.account_id == ProjectMembershipRecord.account_id
            ).where(
                ProjectMembershipRecord.project_id == project_id,
                ProjectMembershipRecord.account_id != account_id,
                ProjectMembershipRecord.project_role == PROJECT_OWNER,
                ProjectMembershipRecord.enabled.is_(True),
                AccountRecord.enabled.is_(True),
            )
        ) or 0
        if not other_count:
            raise _conflict("last_project_owner", "account is the last enabled owner of a project")


def _db_assert_membership_not_last_owner(session, membership) -> None:
    if not membership.enabled or membership.project_role != PROJECT_OWNER:
        return
    other_count = session.scalar(
        select(func.count()).select_from(ProjectMembershipRecord).join(
            AccountRecord, AccountRecord.account_id == ProjectMembershipRecord.account_id
        ).where(
            ProjectMembershipRecord.project_id == membership.project_id,
            ProjectMembershipRecord.account_id != membership.account_id,
            ProjectMembershipRecord.project_role == PROJECT_OWNER,
            ProjectMembershipRecord.enabled.is_(True),
            AccountRecord.enabled.is_(True),
        )
    ) or 0
    if not other_count:
        raise _conflict("last_project_owner", "the last enabled project owner cannot be removed or demoted")


def _memory_assert_membership_not_last_owner(membership) -> None:
    if not membership.enabled or membership.project_role != PROJECT_OWNER:
        return
    others = [
        item for item in _memory_memberships.values()
        if item.project_id == membership.project_id and item.account_id != membership.account_id
        and item.enabled and item.project_role == PROJECT_OWNER
        and (account := _memory_account(item.account_id)) is not None and account.enabled
    ]
    if not others:
        raise _conflict("last_project_owner", "the last enabled project owner cannot be removed or demoted")


def _create_project(payload: ProjectCreateRequest, principal, request_id: str) -> dict:
    code = _normalise_project_code(payload.projectCode)
    display_name = payload.displayName.strip()
    project_id = str(uuid4())
    now = _now()
    with _mutation_lock:
        if not auth.database.enabled:
            if any(item.project_code == code for item in _memory_projects.values()):
                raise _conflict("project_code_exists", "project code already exists")
            owner = _memory_account(payload.ownerAccountId)
            if owner is None or not owner.enabled:
                raise _not_found("account")
            project = _MemoryProjectData(project_id, code, display_name, PROJECT_ACTIVE, 1, principal.account_id, now, now)
            membership = _MemoryMembershipData(project_id, owner.account_id, PROJECT_OWNER, True, 1, principal.account_id, now, now)
            _memory_projects[project_id] = project
            _memory_memberships[(project_id, owner.account_id)] = membership
            set_memory_project(project_id, code, lifecycle_state=PROJECT_ACTIVE, revision=1)
            from .main import alert_advice_knowledge_store
            if alert_advice_knowledge_store.system is not None:
                alert_advice_knowledge_store.system.pin_new_memory_project(project_id)
            set_memory_membership(project_id, owner.account_id, PROJECT_OWNER, revision=1)
            context = _project_context_for_platform(principal, project_id)
            _add_project_audit(None, context, request_id, "project.create", "project", project_id, None, 1, {
                "projectCode": code, "displayName": display_name, "ownerAccountId": owner.account_id,
                "requestFingerprint": _fingerprint({"code": code, "owner": owner.account_id}),
            })
            return _project_payload(project)
        try:
            with auth.database.session() as session:
                owner = session.get(AccountRecord, payload.ownerAccountId)
                if owner is None or not owner.enabled:
                    raise _not_found("account")
                if session.scalar(select(ProjectRecord).where(ProjectRecord.project_code == code)) is not None:
                    raise _conflict("project_code_exists", "project code already exists")
                project = ProjectRecord(
                    project_id=project_id, project_code=code, display_name=display_name,
                    lifecycle_state=PROJECT_ACTIVE, revision=1, created_by_account_id=principal.account_id,
                    created_at=now, updated_at=now,
                )
                session.add(project)
                session.flush()
                session.add(ProjectMembershipRecord(
                    project_id=project_id, account_id=owner.account_id, project_role=PROJECT_OWNER,
                    enabled=True, revision=1, created_by_account_id=principal.account_id,
                    created_at=now, updated_at=now,
                ))
                # Materialize the membership before the audit row so PostgreSQL
                # can validate its foreign keys in this transaction.
                session.flush()
                context = _project_context_for_platform(principal, project_id)
                from .system_alert_knowledge import pin_new_project
                pin_new_project(session, project_id)
                _add_project_audit(session, context, request_id, "project.create", "project", project_id, None, 1, {
                    "projectCode": code, "displayName": display_name, "ownerAccountId": owner.account_id,
                    "requestFingerprint": _fingerprint({"code": code, "owner": owner.account_id}),
                })
                return _project_payload(project)
        except IntegrityError as exc:
            raise _conflict("project_code_exists", "project code already exists") from exc


def _list_projects() -> list[dict]:
    if not auth.database.enabled:
        return [_project_payload(item) for item in sorted(_memory_projects.values(), key=lambda value: value.project_code)]
    with auth.database.session() as session:
        return [_project_payload(item) for item in session.scalars(select(ProjectRecord).order_by(ProjectRecord.project_code)).all()]


def _project(project_id: str):
    if not auth.database.enabled:
        return _memory_projects.get(project_id)
    with auth.database.session() as session:
        return session.get(ProjectRecord, project_id)


def _patch_project(project_id: str, payload: ProjectPatchRequest, principal, request_id: str) -> dict:
    code = _normalise_project_code(payload.projectCode) if payload.projectCode is not None else None
    display_name = payload.displayName.strip() if payload.displayName is not None else None
    with _mutation_lock:
        if not auth.database.enabled:
            current = _memory_projects.get(project_id)
            if current is None:
                raise _not_found("project")
            desired_code = code or current.project_code
            desired_name = display_name or current.display_name
            if desired_code == current.project_code and desired_name == current.display_name:
                _add_project_audit(None, _project_context_for_platform(principal, project_id), request_id,
                                   "project.update", "project", project_id, current.revision, current.revision,
                                   {"noop": True})
                return _project_payload(current)
            if current.revision != payload.expectedRevision:
                raise _conflict("revision_conflict", "project was changed by another request")
            if any(item.project_id != project_id and item.project_code == desired_code for item in _memory_projects.values()):
                raise _conflict("project_code_exists", "project code already exists")
            updated = replace(current, project_code=desired_code, display_name=desired_name, revision=current.revision + 1, updated_at=_now())
            _memory_projects[project_id] = updated
            set_memory_project(project_id, desired_code, lifecycle_state=updated.lifecycle_state, revision=updated.revision)
            context = _project_context_for_platform(principal, project_id)
            _add_project_audit(None, context, request_id, "project.update", "project", project_id, current.revision, updated.revision, {
                "projectCode": {"from": current.project_code, "to": desired_code},
                "displayName": {"from": current.display_name, "to": desired_name},
            })
            return _project_payload(updated)
        try:
            with auth.database.session() as session:
                current = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id).with_for_update())
                if current is None:
                    raise _not_found("project")
                desired_code = code or current.project_code
                desired_name = display_name or current.display_name
                if desired_code == current.project_code and desired_name == current.display_name:
                    _add_project_audit(session, _project_context_for_platform(principal, project_id), request_id,
                                       "project.update", "project", project_id, current.revision, current.revision,
                                       {"noop": True})
                    return _project_payload(current)
                if current.revision != payload.expectedRevision:
                    raise _conflict("revision_conflict", "project was changed by another request")
                previous_revision = current.revision
                previous = {"projectCode": current.project_code, "displayName": current.display_name}
                current.project_code = desired_code
                current.display_name = desired_name
                current.revision += 1
                _add_project_audit(session, _project_context_for_platform(principal, project_id), request_id,
                                   "project.update", "project", project_id, previous_revision, current.revision,
                                   {"before": previous, "after": {"projectCode": desired_code, "displayName": desired_name}})
                session.flush()
                return _project_payload(current)
        except IntegrityError as exc:
            raise _conflict("project_code_exists", "project code already exists") from exc


def _transition_project(project_id: str, expected_revision: int, target_state: str, principal, request_id: str) -> dict:
    action = {PROJECT_SUSPENDED: "project.suspend", PROJECT_ARCHIVED: "project.archive", PROJECT_ACTIVE: "project.restore"}[target_state]
    with _mutation_lock:
        if not auth.database.enabled:
            current = _memory_projects.get(project_id)
            if current is None:
                raise _not_found("project")
            if current.lifecycle_state == target_state:
                _add_project_audit(None, _project_context_for_platform(principal, project_id), request_id,
                                   action, "project", project_id, current.revision, current.revision,
                                   {"noop": True})
                return _project_payload(current)
            if current.revision != expected_revision:
                raise _conflict("revision_conflict", "project was changed by another request")
            if target_state == PROJECT_SUSPENDED and current.lifecycle_state != PROJECT_ACTIVE:
                raise _conflict("lifecycle_conflict", "only an active project can be suspended")
            updated = replace(current, lifecycle_state=target_state, revision=current.revision + 1, updated_at=_now())
            _memory_projects[project_id] = updated
            set_memory_project(project_id, updated.project_code, lifecycle_state=target_state, revision=updated.revision)
            _add_project_audit(None, _project_context_for_platform(principal, project_id), request_id, action,
                               "project", project_id, current.revision, updated.revision,
                               {"lifecycleState": {"from": current.lifecycle_state, "to": target_state}})
            return _project_payload(updated)
        with auth.database.session() as session:
            current = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id).with_for_update())
            if current is None:
                raise _not_found("project")
            if current.lifecycle_state == target_state:
                _add_project_audit(session, _project_context_for_platform(principal, project_id), request_id,
                                   action, "project", project_id, current.revision, current.revision,
                                   {"noop": True})
                return _project_payload(current)
            if current.revision != expected_revision:
                raise _conflict("revision_conflict", "project was changed by another request")
            if target_state == PROJECT_SUSPENDED and current.lifecycle_state != PROJECT_ACTIVE:
                raise _conflict("lifecycle_conflict", "only an active project can be suspended")
            previous_state, previous_revision = current.lifecycle_state, current.revision
            current.lifecycle_state = target_state
            current.revision += 1
            _add_project_audit(session, _project_context_for_platform(principal, project_id), request_id, action,
                               "project", project_id, previous_revision, current.revision,
                               {"lifecycleState": {"from": previous_state, "to": target_state}})
            session.flush()
            return _project_payload(current)


def _list_accounts() -> list[dict]:
    if not auth.database.enabled:
        return [_account_payload(item) for item in sorted(auth.memory_accounts_snapshot(), key=lambda value: value.username)]
    with auth.database.session() as session:
        return [_account_payload(item) for item in session.scalars(select(AccountRecord).order_by(AccountRecord.username)).all()]


def _create_account(payload: AccountCreateRequest, principal, request_id: str) -> dict:
    username = auth._normalise_username(payload.username)
    with _mutation_lock:
        if not auth.database.enabled:
            if any(item.username == username for item in auth.memory_accounts_snapshot()):
                raise _conflict("username_exists", "username already exists")
            created = auth._create_account(
                username, payload.password,
                auth.ROLE_ADMIN if payload.platformRole == PLATFORM_ADMIN else auth.ROLE_OPERATOR,
            )
            account = _memory_account(created.account_id)
            _add_platform_audit(None, principal, request_id, "account.create", "account", created.account_id,
                                None, 1, {"username": username, "platformRole": payload.platformRole})
            return _account_payload(account)
        try:
            with auth.database.session() as session:
                if session.scalar(select(AccountRecord).where(AccountRecord.username == username)) is not None:
                    raise _conflict("username_exists", "username already exists")
                account = AccountRecord(
                    account_id=str(uuid4()), username=username, password_hash=auth._hash_password(payload.password),
                    role=auth.ROLE_ADMIN if payload.platformRole == PLATFORM_ADMIN else auth.ROLE_OPERATOR,
                    platform_role=payload.platformRole, enabled=True, revision=1,
                )
                session.add(account)
                _add_platform_audit(session, principal, request_id, "account.create", "account", account.account_id,
                                    None, 1, {"username": username, "platformRole": payload.platformRole})
                session.flush()
                return _account_payload(account)
        except IntegrityError as exc:
            raise _conflict("username_exists", "username already exists") from exc


def _patch_account(account_id: str, payload: AccountPatchRequest, principal, request_id: str) -> dict:
    with _mutation_lock:
        if not auth.database.enabled:
            current = _memory_account(account_id)
            if current is None:
                raise _not_found("account")
            enabled = current.enabled if payload.enabled is None else payload.enabled
            platform_role = payload.platformRole or current.platform_role
            if enabled == current.enabled and platform_role == current.platform_role:
                _add_platform_audit(None, principal, request_id, "account.update", "account", account_id,
                                    current.revision, current.revision, {"noop": True})
                return _account_payload(current)
            if current.revision != payload.expectedRevision:
                raise _conflict("revision_conflict", "account was changed by another request")
            accounts = auth.memory_accounts_snapshot()
            _assert_not_last_platform_admin(accounts, current, enabled=enabled, platform_role=platform_role)
            if current.enabled and not enabled:
                for membership in list(_memory_memberships.values()):
                    if membership.account_id == account_id:
                        _memory_assert_membership_not_last_owner(membership)
            auth.update_memory_account_for_tests(
                account_id, platform_role=platform_role, enabled=enabled, revision=current.revision + 1
            )
            updated = _memory_account(account_id)
            _add_platform_audit(None, principal, request_id, "account.update", "account", account_id,
                                current.revision, updated.revision,
                                {"enabled": {"from": current.enabled, "to": enabled},
                                 "platformRole": {"from": current.platform_role, "to": platform_role}})
            return _account_payload(updated)
        with auth.database.session() as session:
            current = session.scalar(select(AccountRecord).where(AccountRecord.account_id == account_id).with_for_update())
            if current is None:
                raise _not_found("account")
            enabled = current.enabled if payload.enabled is None else payload.enabled
            platform_role = payload.platformRole or current.platform_role
            if enabled == current.enabled and platform_role == current.platform_role:
                _add_platform_audit(session, principal, request_id, "account.update", "account", account_id,
                                    current.revision, current.revision, {"noop": True})
                return _account_payload(current)
            if current.revision != payload.expectedRevision:
                raise _conflict("revision_conflict", "account was changed by another request")
            accounts = session.scalars(select(AccountRecord).with_for_update()).all()
            _assert_not_last_platform_admin(accounts, current, enabled=enabled, platform_role=platform_role)
            if current.enabled and not enabled:
                _db_assert_account_not_last_owner(session, account_id)
            previous_revision = current.revision
            changes = {"enabled": {"from": current.enabled, "to": enabled},
                       "platformRole": {"from": current.platform_role, "to": platform_role}}
            current.enabled = enabled
            current.platform_role = platform_role
            current.role = auth.ROLE_ADMIN if platform_role == PLATFORM_ADMIN else auth.ROLE_OPERATOR
            current.revision += 1
            _add_platform_audit(session, principal, request_id, "account.update", "account", account_id,
                                previous_revision, current.revision, changes)
            session.flush()
            return _account_payload(current)


def _list_members(project_id: str) -> list[dict]:
    if not auth.database.enabled:
        values = [item for item in _memory_memberships.values() if item.project_id == project_id]
        return [_membership_payload(item, _memory_account(item.account_id)) for item in sorted(values, key=lambda value: value.account_id)]
    with auth.database.session() as session:
        rows = session.execute(
            select(ProjectMembershipRecord, AccountRecord).join(
                AccountRecord, AccountRecord.account_id == ProjectMembershipRecord.account_id
            ).where(ProjectMembershipRecord.project_id == project_id).order_by(AccountRecord.username)
        ).all()
        return [_membership_payload(membership, account) for membership, account in rows]


def _create_membership(project_id: str, payload: MembershipCreateRequest, context: ProjectContext, request_id: str) -> dict:
    _assert_project_role_assignment(context, payload.projectRole)
    with _mutation_lock:
        if not auth.database.enabled:
            account = _memory_account(payload.accountId)
            if account is None or not account.enabled:
                raise _not_found("account")
            existing = _memory_memberships.get((project_id, payload.accountId))
            if existing is not None:
                if existing.enabled and existing.project_role == payload.projectRole:
                    _add_project_audit(None, context, request_id, "membership.create", "membership",
                                       payload.accountId, existing.revision, existing.revision, {"noop": True})
                    return _membership_payload(existing, account)
                raise _conflict("membership_exists", "membership already exists; patch it instead")
            now = _now()
            membership = _MemoryMembershipData(project_id, payload.accountId, payload.projectRole, True, 1,
                                               context.principal.account_id, now, now)
            _memory_memberships[(project_id, payload.accountId)] = membership
            set_memory_membership(project_id, payload.accountId, payload.projectRole, revision=1)
            _add_project_audit(None, context, request_id, "membership.create", "membership", payload.accountId,
                               None, 1, {"projectRole": payload.projectRole, "enabled": True})
            return _membership_payload(membership, account)
        try:
            with auth.database.session() as session:
                session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id).with_for_update())
                account = session.get(AccountRecord, payload.accountId)
                if account is None or not account.enabled:
                    raise _not_found("account")
                existing = session.get(ProjectMembershipRecord, (project_id, payload.accountId))
                if existing is not None:
                    if existing.enabled and existing.project_role == payload.projectRole:
                        _add_project_audit(session, context, request_id, "membership.create", "membership",
                                           payload.accountId, existing.revision, existing.revision, {"noop": True})
                        return _membership_payload(existing, account)
                    raise _conflict("membership_exists", "membership already exists; patch it instead")
                membership = ProjectMembershipRecord(
                    project_id=project_id, account_id=payload.accountId, project_role=payload.projectRole,
                    enabled=True, revision=1, created_by_account_id=context.principal.account_id,
                    # Older pre-release migrations lacked server timestamp defaults.
                    # Explicit values also keep member creation compatible there.
                    created_at=_now(), updated_at=_now(),
                )
                session.add(membership)
                _add_project_audit(session, context, request_id, "membership.create", "membership", payload.accountId,
                                   None, 1, {"projectRole": payload.projectRole, "enabled": True})
                session.flush()
                return _membership_payload(membership, account)
        except IntegrityError as exc:
            raise _conflict("membership_exists", "membership already exists") from exc


def _patch_membership(project_id: str, account_id: str, payload: MembershipPatchRequest,
                      context: ProjectContext, request_id: str) -> dict:
    if payload.projectRole is not None:
        _assert_project_role_assignment(context, payload.projectRole)
    with _mutation_lock:
        if not auth.database.enabled:
            current = _memory_memberships.get((project_id, account_id))
            if current is None:
                raise _not_found("membership")
            if not context.platform_entry and current.project_role == PROJECT_OWNER:
                raise _forbidden("owner_transfer_required", "project owners must be changed through transfer-owner")
            role = payload.projectRole or current.project_role
            enabled = current.enabled if payload.enabled is None else payload.enabled
            if role == current.project_role and enabled == current.enabled:
                _add_project_audit(None, context, request_id, "membership.update", "membership", account_id,
                                   current.revision, current.revision, {"noop": True})
                return _membership_payload(current, _memory_account(account_id))
            if current.revision != payload.expectedRevision:
                raise _conflict("revision_conflict", "membership was changed by another request")
            account = _memory_account(account_id)
            if enabled and (account is None or not account.enabled):
                raise _conflict("account_disabled", "a disabled account cannot have an enabled membership")
            if current.project_role == PROJECT_OWNER and (role != PROJECT_OWNER or not enabled):
                _memory_assert_membership_not_last_owner(current)
            updated = replace(current, project_role=role, enabled=enabled, revision=current.revision + 1, updated_at=_now())
            _memory_memberships[(project_id, account_id)] = updated
            set_memory_membership(project_id, account_id, role, enabled=enabled, revision=updated.revision)
            _add_project_audit(None, context, request_id, "membership.update", "membership", account_id,
                               current.revision, updated.revision,
                               {"projectRole": {"from": current.project_role, "to": role},
                                "enabled": {"from": current.enabled, "to": enabled}})
            return _membership_payload(updated, account)
        with auth.database.session() as session:
            session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id).with_for_update())
            current = session.scalar(select(ProjectMembershipRecord).where(
                ProjectMembershipRecord.project_id == project_id,
                ProjectMembershipRecord.account_id == account_id,
            ).with_for_update())
            if current is None:
                raise _not_found("membership")
            if not context.platform_entry and current.project_role == PROJECT_OWNER:
                raise _forbidden("owner_transfer_required", "project owners must be changed through transfer-owner")
            role = payload.projectRole or current.project_role
            enabled = current.enabled if payload.enabled is None else payload.enabled
            account = session.get(AccountRecord, account_id)
            if role == current.project_role and enabled == current.enabled:
                _add_project_audit(session, context, request_id, "membership.update", "membership", account_id,
                                   current.revision, current.revision, {"noop": True})
                return _membership_payload(current, account)
            if current.revision != payload.expectedRevision:
                raise _conflict("revision_conflict", "membership was changed by another request")
            if enabled and (account is None or not account.enabled):
                raise _conflict("account_disabled", "a disabled account cannot have an enabled membership")
            if current.project_role == PROJECT_OWNER and (role != PROJECT_OWNER or not enabled):
                _db_assert_membership_not_last_owner(session, current)
            previous_role, previous_enabled, previous_revision = current.project_role, current.enabled, current.revision
            current.project_role = role
            current.enabled = enabled
            current.revision += 1
            _add_project_audit(session, context, request_id, "membership.update", "membership", account_id,
                               previous_revision, current.revision,
                               {"projectRole": {"from": previous_role, "to": role},
                                "enabled": {"from": previous_enabled, "to": enabled}})
            session.flush()
            return _membership_payload(current, account)


def _delete_membership(project_id: str, account_id: str, expected_revision: int,
                       context: ProjectContext, request_id: str) -> None:
    with _mutation_lock:
        if not auth.database.enabled:
            current = _memory_memberships.get((project_id, account_id))
            if current is None:
                _add_project_audit(None, context, request_id, "membership.delete", "membership", account_id,
                                   None, None, {"noop": True})
                return
            if not context.platform_entry and current.project_role == PROJECT_OWNER:
                raise _forbidden("owner_transfer_required", "project owners must be changed through transfer-owner")
            if current.revision != expected_revision:
                raise _conflict("revision_conflict", "membership was changed by another request")
            _memory_assert_membership_not_last_owner(current)
            del _memory_memberships[(project_id, account_id)]
            remove_memory_membership(project_id, account_id)
            _add_project_audit(None, context, request_id, "membership.delete", "membership", account_id,
                               current.revision, None, {"projectRole": current.project_role, "enabled": current.enabled})
            return
        with auth.database.session() as session:
            session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id).with_for_update())
            current = session.scalar(select(ProjectMembershipRecord).where(
                ProjectMembershipRecord.project_id == project_id,
                ProjectMembershipRecord.account_id == account_id,
            ).with_for_update())
            if current is None:
                _add_project_audit(session, context, request_id, "membership.delete", "membership", account_id,
                                   None, None, {"noop": True})
                return
            if not context.platform_entry and current.project_role == PROJECT_OWNER:
                raise _forbidden("owner_transfer_required", "project owners must be changed through transfer-owner")
            if current.revision != expected_revision:
                raise _conflict("revision_conflict", "membership was changed by another request")
            _db_assert_membership_not_last_owner(session, current)
            previous_revision, previous_role, previous_enabled = current.revision, current.project_role, current.enabled
            session.delete(current)
            _add_project_audit(session, context, request_id, "membership.delete", "membership", account_id,
                               previous_revision, None, {"projectRole": previous_role, "enabled": previous_enabled})


def _transfer_owner(project_id: str, payload: OwnerTransferRequest,
                    context: ProjectContext, request_id: str) -> dict:
    if payload.fromAccountId == payload.toAccountId:
        raise _conflict("owner_transfer_same_account", "owner transfer requires two different accounts")
    if not context.platform_entry and context.principal.account_id != payload.fromAccountId:
        raise _forbidden("owner_transfer_forbidden", "a project owner can transfer only their own ownership")
    with _mutation_lock:
        if not auth.database.enabled:
            source = _memory_memberships.get((project_id, payload.fromAccountId))
            target = _memory_memberships.get((project_id, payload.toAccountId))
            target_account = _memory_account(payload.toAccountId)
            if source is None or target is None:
                raise _not_found("membership")
            if source.project_role != PROJECT_OWNER or not source.enabled:
                raise _conflict("source_not_owner", "source membership is not an enabled owner")
            if not target.enabled or target_account is None or not target_account.enabled:
                raise _conflict("target_not_eligible", "target must be an enabled member with an enabled account")
            if source.revision != payload.expectedFromRevision or target.revision != payload.expectedToRevision:
                raise _conflict("revision_conflict", "membership was changed by another request")
            now = _now()
            source_updated = replace(source, project_role=PROJECT_USER, revision=source.revision + 1, updated_at=now)
            target_updated = replace(target, project_role=PROJECT_OWNER, revision=target.revision + 1, updated_at=now)
            _memory_memberships[(project_id, source.account_id)] = source_updated
            _memory_memberships[(project_id, target.account_id)] = target_updated
            set_memory_membership(project_id, source.account_id, PROJECT_USER, revision=source_updated.revision)
            set_memory_membership(project_id, target.account_id, PROJECT_OWNER, revision=target_updated.revision)
            _add_project_audit(None, context, request_id, "membership.transfer_owner", "project", project_id,
                               None, None, {"fromAccountId": source.account_id, "toAccountId": target.account_id,
                                            "fromRevision": source_updated.revision, "toRevision": target_updated.revision})
            return {"from": _membership_payload(source_updated, _memory_account(source.account_id)),
                    "to": _membership_payload(target_updated, target_account)}
        with auth.database.session() as session:
            session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id).with_for_update())
            source = session.scalar(select(ProjectMembershipRecord).where(
                ProjectMembershipRecord.project_id == project_id,
                ProjectMembershipRecord.account_id == payload.fromAccountId,
            ).with_for_update())
            target = session.scalar(select(ProjectMembershipRecord).where(
                ProjectMembershipRecord.project_id == project_id,
                ProjectMembershipRecord.account_id == payload.toAccountId,
            ).with_for_update())
            target_account = session.get(AccountRecord, payload.toAccountId)
            if source is None or target is None:
                raise _not_found("membership")
            if source.project_role != PROJECT_OWNER or not source.enabled:
                raise _conflict("source_not_owner", "source membership is not an enabled owner")
            if not target.enabled or target_account is None or not target_account.enabled:
                raise _conflict("target_not_eligible", "target must be an enabled member with an enabled account")
            if source.revision != payload.expectedFromRevision or target.revision != payload.expectedToRevision:
                raise _conflict("revision_conflict", "membership was changed by another request")
            source.project_role = PROJECT_USER
            source.revision += 1
            target.project_role = PROJECT_OWNER
            target.revision += 1
            _add_project_audit(session, context, request_id, "membership.transfer_owner", "project", project_id,
                               None, None, {"fromAccountId": source.account_id, "toAccountId": target.account_id,
                                            "fromRevision": source.revision, "toRevision": target.revision})
            session.flush()
            source_account = session.get(AccountRecord, payload.fromAccountId)
            return {"from": _membership_payload(source, source_account),
                    "to": _membership_payload(target, target_account)}


def _accessible_projects(principal) -> list[dict]:
    if principal.platform_role == PLATFORM_ADMIN:
        values = _list_projects()
        return [{**item, "projectRole": None, "membershipRevision": None,
                 "platformEntry": True, "capabilities": sorted(_lifecycle_capabilities(
                     item["lifecycleState"], None, PROJECT_OWNER_CAPABILITIES, platform_entry=True
                 ))} for item in values]
    if not auth.database.enabled:
        memberships = [item for item in _memory_memberships.values() if item.account_id == principal.account_id and item.enabled]
        result = []
        for membership in memberships:
            project = _memory_projects.get(membership.project_id)
            if project is None or (project.lifecycle_state == PROJECT_ARCHIVED and membership.project_role != PROJECT_OWNER):
                continue
            result.append({**_project_payload(project), "projectRole": membership.project_role,
                           "membershipRevision": membership.revision, "platformEntry": False,
                           "capabilities": _capabilities(membership.project_role, project.lifecycle_state)})
        return sorted(result, key=lambda item: item["projectCode"])
    with auth.database.session() as session:
        rows = session.execute(
            select(ProjectRecord, ProjectMembershipRecord).join(
                ProjectMembershipRecord, ProjectMembershipRecord.project_id == ProjectRecord.project_id
            ).where(
                ProjectMembershipRecord.account_id == principal.account_id,
                ProjectMembershipRecord.enabled.is_(True),
            ).order_by(ProjectRecord.project_code)
        ).all()
        return [
            {**_project_payload(project), "projectRole": membership.project_role,
             "membershipRevision": membership.revision, "platformEntry": False,
             "capabilities": _capabilities(membership.project_role, project.lifecycle_state)}
            for project, membership in rows
            if project.lifecycle_state != PROJECT_ARCHIVED or membership.project_role == PROJECT_OWNER
        ]


def _audit_page(project_id: str | None, limit: int, cursor: str | None, filters: dict | None = None) -> dict:
    """Keyset page; expose explicit metadata only, never arbitrary audit payloads."""
    filters = filters or {}
    fingerprint = sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest() if filters else None
    boundary = None
    if cursor:
        try:
            raw = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if not isinstance(raw, list) or len(raw) != 4 or raw[0] != project_id or raw[3] != fingerprint:
                raise ValueError()
            moment = datetime.fromisoformat(raw[1])
            if moment.tzinfo is None or not isinstance(raw[2], str) or not raw[2]:
                raise ValueError()
            boundary = (moment, raw[2])
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise _error(422, 'audit_cursor_invalid', 'audit cursor is invalid for this scope')
    fields = {
        'auditId': 'audit_id', 'occurredAt': 'occurred_at', 'requestId': 'request_id',
        'actorAccountId': 'actor_account_id', 'actorServicePrincipalId': 'actor_service_principal_id',
        'platformRole': 'platform_role', 'projectId': 'project_id', 'projectRole': 'project_role',
        'action': 'action', 'targetType': 'target_type', 'targetId': 'target_id',
        'previousRevision': 'previous_revision', 'newRevision': 'new_revision',
        'outcome': 'outcome', 'failureCode': 'failure_code',
    }
    if not auth.database.enabled:
        from .project_auth import memory_platform_entry_audits
        with _mutation_lock:
            rows = list(_memory_platform_audits if project_id is None else _memory_project_audits)
        if project_id is not None:
            rows += memory_platform_entry_audits()
            rows = [r for r in rows if r.get('projectId') == project_id]
        rows = [{key: row.get(key) for key in fields} for row in rows]
        for key, value in filters.items():
            if key in ('since', 'until'):
                moment = datetime.fromisoformat(value)
                rows = [r for r in rows if (datetime.fromisoformat(r['occurredAt']) >= moment if key == 'since' else datetime.fromisoformat(r['occurredAt']) <= moment)]
            else:
                rows = [r for r in rows if r.get(key) == value]
        rows.sort(key=lambda r: (r['occurredAt'], r['auditId']), reverse=True)
        if boundary:
            rows = [r for r in rows if (datetime.fromisoformat(r['occurredAt']), r['auditId']) < boundary]
        rows = rows[:limit + 1]
    else:
        model = PlatformAuditEventRecord if project_id is None else ProjectAuditEventRecord
        # SQLite server timestamps omit fractional seconds, while bound datetimes
        # include them. Compare normalized time values, not unequal text formats.
        sqlite = auth.database.engine.dialect.name == 'sqlite'
        time_column = func.julianday(model.occurred_at) if sqlite else model.occurred_at
        selected = {key: getattr(model, attr) for key, attr in fields.items() if hasattr(model, attr)}
        query = select(*(column.label(key) for key, column in selected.items()))
        if project_id is not None:
            query = query.where(model.project_id == project_id)
        for key, value in filters.items():
            if key in ('since', 'until'):
                moment = datetime.fromisoformat(value)
                bound = func.julianday(moment) if sqlite else moment
                query = query.where(time_column >= bound if key == 'since' else time_column <= bound)
            else:
                query = query.where(selected[key] == value)
        if boundary:
            time_boundary = func.julianday(boundary[0]) if sqlite else boundary[0]
            query = query.where(tuple_(time_column, model.audit_id) < tuple_(time_boundary, boundary[1]))
        with auth.database.session() as session:
            values = session.execute(query.order_by(time_column.desc(), model.audit_id.desc()).limit(limit + 1)).mappings().all()
            rows = [{key: (_timestamp(row[key]) if key == 'occurredAt' else row.get(key)) for key in fields} for row in values]
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        next_cursor = base64.urlsafe_b64encode(json.dumps([project_id, last['occurredAt'], last['auditId'], fingerprint]).encode()).decode()
    return {'events': page, 'nextCursor': next_cursor}


def create_project_management_router() -> APIRouter:
    router = APIRouter(prefix="/aiyoloapi", tags=["project-management"])

    @router.get("/projects")
    @router.get("/platform/projects")
    async def list_projects(principal=Depends(require_platform_capability(PLATFORM_PROJECTS_MANAGE))):
        return {"projects": _list_projects()}

    @router.post("/projects", status_code=201)
    @router.post("/platform/projects", status_code=201)
    async def create_project(payload: ProjectCreateRequest, request: Request,
                             principal=Depends(require_platform_capability(PLATFORM_PROJECTS_MANAGE))):
        request_id = _request_id(request)
        return _platform_write(
            principal, request_id, "project.create", "project", payload.projectCode,
            lambda: _create_project(payload, principal, request_id),
        )

    @router.get("/projects/{project_id}")
    async def get_project(context=Depends(require_project_capability("project.read"))):
        project = _project(context.project_id)
        if project is None:
            raise _not_found("project")
        return _project_payload(project)

    @router.patch("/projects/{project_id}")
    @router.patch("/platform/projects/{project_id}")
    async def patch_project(project_id: str, payload: ProjectPatchRequest, request: Request,
                            principal=Depends(require_platform_capability(PLATFORM_PROJECTS_MANAGE))):
        request_id = _request_id(request)
        return _platform_write(principal, request_id, "project.update", "project", project_id,
                               lambda: _patch_project(project_id, payload, principal, request_id))

    @router.post("/projects/{project_id}/suspend")
    @router.post("/platform/projects/{project_id}/suspend")
    async def suspend_project(project_id: str, payload: RevisionRequest, request: Request,
                              principal=Depends(require_platform_capability(PLATFORM_PROJECTS_MANAGE))):
        request_id = _request_id(request)
        return _platform_write(principal, request_id, "project.suspend", "project", project_id,
                               lambda: _transition_project(project_id, payload.expectedRevision, PROJECT_SUSPENDED,
                                                           principal, request_id))

    @router.post("/projects/{project_id}/archive")
    @router.post("/platform/projects/{project_id}/archive")
    async def archive_project(project_id: str, payload: RevisionRequest, request: Request,
                              principal=Depends(require_platform_capability(PLATFORM_PROJECTS_MANAGE))):
        request_id = _request_id(request)
        return _platform_write(principal, request_id, "project.archive", "project", project_id,
                               lambda: _transition_project(project_id, payload.expectedRevision, PROJECT_ARCHIVED,
                                                           principal, request_id))

    @router.post("/projects/{project_id}/restore")
    @router.post("/platform/projects/{project_id}/restore")
    async def restore_project(project_id: str, payload: RevisionRequest, request: Request,
                              principal=Depends(require_platform_capability(PLATFORM_PROJECTS_MANAGE))):
        request_id = _request_id(request)
        return _platform_write(principal, request_id, "project.restore", "project", project_id,
                               lambda: _transition_project(project_id, payload.expectedRevision, PROJECT_ACTIVE,
                                                           principal, request_id))

    @router.get("/platform/accounts")
    async def list_accounts(principal=Depends(require_platform_capability(PLATFORM_ACCOUNTS_MANAGE))):
        return {"accounts": _list_accounts()}

    @router.post("/platform/accounts", status_code=201)
    async def create_account(payload: AccountCreateRequest, request: Request,
                             principal=Depends(require_platform_capability(PLATFORM_ACCOUNTS_MANAGE))):
        request_id = _request_id(request)
        return _platform_write(principal, request_id, "account.create", "account", payload.username,
                               lambda: _create_account(payload, principal, request_id))

    @router.patch("/platform/accounts/{account_id}")
    async def patch_account(account_id: str, payload: AccountPatchRequest, request: Request,
                            principal=Depends(require_platform_capability(PLATFORM_ACCOUNTS_MANAGE))):
        request_id = _request_id(request)
        return _platform_write(principal, request_id, "account.update", "account", account_id,
                               lambda: _patch_account(account_id, payload, principal, request_id))

    @router.get("/auth/projects")
    async def auth_projects(principal=Depends(require_principal)):
        return {"projects": _accessible_projects(principal), "contractVersion": "m33-v1"}

    @router.get("/projects/{project_id}/members")
    async def list_members(project_id: str,
                           context=Depends(require_project_capability(PROJECT_MEMBERS_MANAGE))):
        return {"members": _list_members(project_id), "projectRevision": context.project_revision}

    @router.post("/projects/{project_id}/members", status_code=201)
    async def create_membership(project_id: str, payload: MembershipCreateRequest, request: Request,
                                context=Depends(require_project_capability(PROJECT_MEMBERS_MANAGE))):
        request_id = _request_id(request)
        return _project_write(context, request_id, "membership.create", "membership", payload.accountId,
                              lambda: _create_membership(project_id, payload, context, request_id))

    @router.patch("/projects/{project_id}/members/{account_id}")
    async def patch_membership(project_id: str, account_id: str, payload: MembershipPatchRequest,
                               request: Request,
                               context=Depends(require_project_capability(PROJECT_MEMBERS_MANAGE))):
        request_id = _request_id(request)
        return _project_write(context, request_id, "membership.update", "membership", account_id,
                              lambda: _patch_membership(project_id, account_id, payload, context, request_id))

    @router.delete("/projects/{project_id}/members/{account_id}", status_code=204)
    async def delete_membership(project_id: str, account_id: str, request: Request,
                                expectedRevision: int = Query(ge=1),
                                context=Depends(require_project_capability(PROJECT_MEMBERS_MANAGE))):
        request_id = _request_id(request)
        _project_write(context, request_id, "membership.delete", "membership", account_id,
                       lambda: _delete_membership(project_id, account_id, expectedRevision, context, request_id))

    @router.post("/projects/{project_id}/transfer-owner")
    async def transfer_owner(project_id: str, payload: OwnerTransferRequest, request: Request,
                             context=Depends(require_project_capability(PROJECT_MEMBERS_MANAGE))):
        request_id = _request_id(request)
        return _project_write(context, request_id, "membership.transfer_owner", "project", project_id,
                              lambda: _transfer_owner(project_id, payload, context, request_id))

    @router.get('/platform/audit')
    async def platform_audit(limit: int = Query(default=25, ge=1, le=100),
                             cursor: str | None = Query(default=None, max_length=512),
                             filters=Depends(audit_filters),
                             principal=Depends(require_platform_capability(PLATFORM_AUDIT_READ))):
        return _audit_page(None, limit, cursor, filters)

    @router.get('/projects/{project_id}/audit')
    async def project_audit(project_id: str, limit: int = Query(default=25, ge=1, le=100),
                            cursor: str | None = Query(default=None, max_length=512),
                            filters=Depends(audit_filters),
                            context=Depends(require_project_capability(PROJECT_AUDIT_READ))):
        return _audit_page(project_id, limit, cursor, filters)

    return router


def reset_memory_project_management_for_tests() -> None:
    with _mutation_lock:
        _memory_projects.clear()
        _memory_memberships.clear()
        _memory_project_audits.clear()
        _memory_platform_audits.clear()


def memory_audits_for_tests() -> dict[str, tuple[dict, ...]]:
    with _mutation_lock:
        return {"project": tuple(_memory_project_audits), "platform": tuple(_memory_platform_audits)}
