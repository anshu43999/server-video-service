from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4
import logging
import json

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from . import auth
from .auth import Principal
from .database import DEFAULT_PROJECT_ID, ProjectAuditEventRecord, ProjectMembershipRecord, ProjectRecord
from .config import settings


PLATFORM_ADMIN = auth.PLATFORM_ADMIN
NORMAL_USER = auth.NORMAL_USER
PROJECT_OWNER = "PROJECT_OWNER"
PROJECT_USER = "PROJECT_USER"

PROJECT_ACTIVE = "ACTIVE"
PROJECT_SUSPENDED = "SUSPENDED"
PROJECT_ARCHIVED = "ARCHIVED"

PLATFORM_PROJECTS_MANAGE = "platform.projects.manage"
PLATFORM_ACCOUNTS_MANAGE = "platform.accounts.manage"
PLATFORM_MODELS_MANAGE = "platform.models.manage"
PLATFORM_AUDIT_READ = "platform.audit.read"
PLATFORM_OBSERVABILITY_READ = "platform.observability.read"
PLATFORM_LEGACY_MIGRATION_MANAGE = "platform.legacy_migration.manage"
PLATFORM_ALERT_KNOWLEDGE_MANAGE = "platform.alert_knowledge.manage"

PROJECT_READ = "project.read"
PROJECT_MEMBERS_MANAGE = "project.members.manage"
PROJECT_STREAMS_MANAGE = "project.streams.manage"
PROJECT_RULES_MANAGE = "project.rules.manage"
PROJECT_MODELS_ASSIGN = "project.models.assign"
PROJECT_SCENES_MANAGE = "project.scenes.manage"
PROJECT_SCENES_APPROVE = "project.scenes.approve"
PROJECT_SETTINGS_MANAGE = "project.settings.manage"
PROJECT_INSPECTION_USE = "project.inspection.use"
PROJECT_STREAMS_VIEW = "project.streams.view"
PROJECT_ALERTS_READ = "project.alerts.read"
PROJECT_ALERTS_DISPOSE = "project.alerts.dispose"
PROJECT_ALERT_KNOWLEDGE_READ = "project.alert_knowledge.read"
PROJECT_ALERT_KNOWLEDGE_MANAGE = "project.alert_knowledge.manage"
PROJECT_ALERT_ADVICE_GENERATE = "project.alert_advice.generate"
PROJECT_ALERT_ADVICE_READ = "project.alert_advice.read"
PROJECT_ALERT_ADVICE_HISTORY_READ = "project.alert_advice.history.read"
PROJECT_EXPORTS_CREATE = "project.exports.create"
PROJECT_AUDIT_READ = "project.audit.read"
PROJECT_SERVICE_PRINCIPALS_MANAGE = "project.service_principals.manage"

PLATFORM_CAPABILITIES = frozenset(
    {
        PLATFORM_PROJECTS_MANAGE,
        PLATFORM_ACCOUNTS_MANAGE,
        PLATFORM_MODELS_MANAGE,
        PLATFORM_AUDIT_READ,
        PLATFORM_OBSERVABILITY_READ,
        PLATFORM_LEGACY_MIGRATION_MANAGE,
        PLATFORM_ALERT_KNOWLEDGE_MANAGE,
    }
)

PROJECT_USER_CAPABILITIES = frozenset(
    {
        PROJECT_READ,
        PROJECT_INSPECTION_USE,
        PROJECT_STREAMS_VIEW,
        PROJECT_ALERTS_READ,
        PROJECT_ALERTS_DISPOSE,
        PROJECT_ALERT_KNOWLEDGE_READ,
        PROJECT_ALERT_ADVICE_GENERATE,
        PROJECT_ALERT_ADVICE_READ,
        PROJECT_ALERT_ADVICE_HISTORY_READ,
    }
)

PROJECT_OWNER_CAPABILITIES = frozenset(
    {
        *PROJECT_USER_CAPABILITIES,
        PROJECT_MEMBERS_MANAGE,
        PROJECT_STREAMS_MANAGE,
        PROJECT_RULES_MANAGE,
        PROJECT_MODELS_ASSIGN,
        PROJECT_SCENES_MANAGE,
        PROJECT_SCENES_APPROVE,
        PROJECT_SETTINGS_MANAGE,
        PROJECT_ALERT_KNOWLEDGE_MANAGE,
        PROJECT_EXPORTS_CREATE,
        PROJECT_AUDIT_READ,
        PROJECT_SERVICE_PRINCIPALS_MANAGE,
    }
)

PROJECT_ROLE_CAPABILITIES = {
    PROJECT_OWNER: PROJECT_OWNER_CAPABILITIES,
    PROJECT_USER: PROJECT_USER_CAPABILITIES,
}


@dataclass(frozen=True)
class ProjectContext:
    principal: Principal
    project_id: str
    project_code: str
    lifecycle_state: str
    project_role: str | None
    capabilities: frozenset[str]
    membership_revision: int | None
    project_revision: int
    platform_entry: bool = False


@dataclass(frozen=True)
class _MemoryProject:
    project_id: str
    project_code: str
    lifecycle_state: str
    revision: int


@dataclass(frozen=True)
class _MemoryMembership:
    project_id: str
    account_id: str
    project_role: str
    enabled: bool
    revision: int


_memory_lock = RLock()
_memory_projects: dict[str, _MemoryProject] = {}
_memory_memberships: dict[tuple[str, str], _MemoryMembership] = {}
_memory_platform_entries: list[dict] = []


def memory_project_lifecycle(project_id: str) -> str | None:
    with _memory_lock:
        project = _memory_projects.get(project_id)
        return project.lifecycle_state if project else None


def authorization_error(capability: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "capability_required",
            "message": "current principal does not have the required capability",
            "capability": capability,
        },
    )


def project_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "project_not_found", "message": "project was not found"},
    )


def project_context_required_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "project_context_required",
            "message": "an explicit project context is required",
        },
    )


def _project_id(scope, *, allow_legacy: bool = True) -> str:
    path_params = getattr(scope, "path_params", {}) or {}
    project_id = path_params.get("project_id") or path_params.get("projectId")
    if not project_id:
        project_id = scope.headers.get("x-project-id")
    if project_id is not None and not project_id.strip():
        raise project_context_required_error()
    if not project_id:
        if not allow_legacy:
            raise project_context_required_error()
        project_id = _legacy_project(scope)
    return project_id.strip()


def _legacy_project(scope) -> str:
    """Explicit default-only migration window; normal authorization still follows."""
    until = settings.legacy_project_until
    if settings.legacy_project_id != DEFAULT_PROJECT_ID or not until:
        raise project_context_required_error()
    try:
        deadline = datetime.fromisoformat(until.replace("Z", "+00:00"))
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    except (ValueError, TypeError):
        raise project_context_required_error()
    if not 0 < remaining <= 7 * 86400:
        raise project_context_required_error()
    if auth.database.enabled:
        with auth.database.session() as session:
            projects = session.execute(select(ProjectRecord.project_id).limit(2)).scalars().all()
    else:
        with _memory_lock:
            projects = list(_memory_projects)[:2]
    # Suspended/archived projects also count: creating another project closes the window.
    if projects != [DEFAULT_PROJECT_ID]:
        raise project_context_required_error()
    state = getattr(scope, "state", None)
    if state is not None:
        state.legacy_project_mapping = True
        state.legacy_project_until = deadline.strftime("%a, %d %b %Y %H:%M:%S GMT")
    logging.getLogger("aiyolo.requests").warning(json.dumps({
        "event": "legacy_project_mapping", "projectId": DEFAULT_PROJECT_ID,
        "accountId": getattr(state, "account_id", None),
        "requestId": getattr(state, "request_id", None), "expiresAt": deadline.isoformat(),
    }))
    return DEFAULT_PROJECT_ID


def _lifecycle_capabilities(
    lifecycle_state: str,
    project_role: str | None,
    capabilities: frozenset[str],
    *,
    platform_entry: bool,
) -> frozenset[str]:
    if lifecycle_state == PROJECT_ACTIVE:
        return capabilities
    if lifecycle_state == PROJECT_SUSPENDED:
        allowed = {
            PROJECT_READ,
            PROJECT_ALERTS_READ,
            PROJECT_ALERT_KNOWLEDGE_READ,
            PROJECT_ALERT_ADVICE_READ,
            PROJECT_ALERT_ADVICE_HISTORY_READ,
            PROJECT_AUDIT_READ,
            PROJECT_MEMBERS_MANAGE,
            PROJECT_SETTINGS_MANAGE,
            PROJECT_SERVICE_PRINCIPALS_MANAGE,
        }
        return frozenset(capabilities.intersection(allowed))
    if lifecycle_state == PROJECT_ARCHIVED and (platform_entry or project_role == PROJECT_OWNER):
        return frozenset(capabilities.intersection({
            PROJECT_READ, PROJECT_ALERTS_READ, PROJECT_AUDIT_READ,
            PROJECT_ALERT_KNOWLEDGE_READ, PROJECT_ALERT_ADVICE_READ,
            PROJECT_ALERT_ADVICE_HISTORY_READ,
        }))
    return frozenset()


def _load_project_state(
    project_id: str,
    account_id: str,
) -> tuple[_MemoryProject | None, _MemoryMembership | None]:
    if not auth.database.enabled:
        with _memory_lock:
            return (
                _memory_projects.get(project_id),
                _memory_memberships.get((project_id, account_id)),
            )
    with auth.database.session() as session:
        project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
        membership = session.scalar(
            select(ProjectMembershipRecord).where(
                ProjectMembershipRecord.project_id == project_id,
                ProjectMembershipRecord.account_id == account_id,
            )
        )
        if project is None:
            return None, None
        project_value = _MemoryProject(
            project_id=project.project_id,
            project_code=project.project_code,
            lifecycle_state=project.lifecycle_state,
            revision=project.revision,
        )
        membership_value = None
        if membership is not None:
            membership_value = _MemoryMembership(
                project_id=membership.project_id,
                account_id=membership.account_id,
                project_role=membership.project_role,
                enabled=membership.enabled,
                revision=membership.revision,
            )
        return project_value, membership_value


def resolve_project_context(principal: Principal, project_id: str) -> ProjectContext:
    if principal.legacy:
        raise auth.authentication_error("account session")
    project, membership = _load_project_state(project_id, principal.account_id)
    if project is None:
        raise project_not_found_error()

    platform_entry = principal.platform_role == PLATFORM_ADMIN
    active_membership = membership if membership is not None and membership.enabled else None
    if not platform_entry and active_membership is None:
        raise project_not_found_error()
    if project.lifecycle_state == PROJECT_ARCHIVED and not platform_entry:
        if active_membership is None or active_membership.project_role != PROJECT_OWNER:
            raise project_not_found_error()

    project_role = active_membership.project_role if active_membership is not None else None
    role_capabilities = (
        PROJECT_OWNER_CAPABILITIES if platform_entry else PROJECT_ROLE_CAPABILITIES.get(project_role, frozenset())
    )
    capabilities = _lifecycle_capabilities(
        project.lifecycle_state,
        project_role,
        role_capabilities,
        platform_entry=platform_entry,
    )
    return ProjectContext(
        principal=principal,
        project_id=project.project_id,
        project_code=project.project_code,
        lifecycle_state=project.lifecycle_state,
        project_role=project_role,
        capabilities=capabilities,
        membership_revision=active_membership.revision if active_membership is not None else None,
        project_revision=project.revision,
        platform_entry=platform_entry,
    )


async def require_principal(request: Request) -> Principal:
    principal = auth.authenticate(request)
    if principal is None or principal.legacy:
        raise auth.authentication_error()
    request.state.account_id = principal.account_id
    return principal


def require_platform_capability(capability: str):
    if capability not in PLATFORM_CAPABILITIES:
        raise ValueError(f"unknown platform capability: {capability}")

    async def dependency(request: Request) -> Principal:
        principal = await require_principal(request)
        if principal.platform_role != PLATFORM_ADMIN:
            raise authorization_error(capability)
        return principal

    return dependency


def require_project_capability(capability: str):
    if capability not in PROJECT_OWNER_CAPABILITIES:
        raise ValueError(f"unknown project capability: {capability}")

    async def dependency(request: Request) -> ProjectContext:
        principal = await require_principal(request)
        context = resolve_project_context(principal, _project_id(request))
        request.state.project_id = context.project_id
        if capability not in context.capabilities:
            raise authorization_error(capability)
        if context.platform_entry:
            _audit_platform_entry(context, request, "HTTP")
        return context

    return dependency


def resolve_websocket_project_context(websocket, capability: str, *, audit: bool = True) -> ProjectContext:
    if capability not in PROJECT_OWNER_CAPABILITIES:
        raise ValueError(f"unknown project capability: {capability}")
    principal = auth.authenticate_websocket(websocket)
    if principal is None or principal.legacy:
        raise auth.authentication_error()
    context = resolve_project_context(principal, _project_id(websocket))
    if hasattr(websocket, 'state'):
        websocket.state.account_id = principal.account_id
        websocket.state.project_id = context.project_id
    if capability not in context.capabilities:
        raise authorization_error(capability)
    if context.platform_entry and audit:
        _audit_platform_entry(context, websocket, "WEBSOCKET")
    return context


def _audit_platform_entry(context: ProjectContext, scope, transport: str) -> None:
    request_id = scope.headers.get("x-request-id", "").strip()[:128] or str(uuid4())
    if not auth.database.enabled:
        with _memory_lock:
            _memory_platform_entries.append({
                "auditId": str(uuid4()),
                "occurredAt": datetime.now(timezone.utc).isoformat(),
                "requestId": request_id,
                "actorAccountId": context.principal.account_id,
                "projectId": context.project_id,
                "action": "project.platform_entry",
                "transport": transport,
            })
        return
    with auth.database.session() as session:
        session.add(ProjectAuditEventRecord(
            audit_id=str(uuid4()), request_id=request_id,
            actor_account_id=context.principal.account_id,
            platform_role=context.principal.platform_role,
            project_id=context.project_id, project_role=context.project_role,
            action="project.platform_entry", target_type="project", target_id=context.project_id,
            change_summary={"transport": transport}, outcome="SUCCESS",
        ))


def memory_platform_entry_audits() -> list[dict]:
    with _memory_lock:
        return [{**entry, 'platformRole': PLATFORM_ADMIN, 'targetType': 'project',
                 'targetId': entry['projectId'], 'outcome': 'SUCCESS'}
                for entry in _memory_platform_entries]


def set_memory_project(
    project_id: str,
    project_code: str,
    *,
    lifecycle_state: str = PROJECT_ACTIVE,
    revision: int = 1,
) -> None:
    with _memory_lock:
        _memory_projects[project_id] = _MemoryProject(project_id, project_code, lifecycle_state, revision)


def set_memory_membership(
    project_id: str,
    account_id: str,
    project_role: str,
    *,
    enabled: bool = True,
    revision: int = 1,
) -> None:
    with _memory_lock:
        _memory_memberships[(project_id, account_id)] = _MemoryMembership(
            project_id,
            account_id,
            project_role,
            enabled,
            revision,
        )


def reset_memory_project_authorization_for_tests() -> None:
    with _memory_lock:
        _memory_projects.clear()
        _memory_memberships.clear()
        _memory_platform_entries.clear()


def remove_memory_membership(project_id: str, account_id: str) -> None:
    with _memory_lock:
        _memory_memberships.pop((project_id, account_id), None)


# Compatibility aliases used by focused authorization fixtures.
set_memory_project_for_tests = set_memory_project
set_memory_membership_for_tests = set_memory_membership
