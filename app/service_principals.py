"""Non-human identities. Deliberately not accepted by human auth dependencies.

Bearer credentials require TLS. Timestamp/nonce headers reject captured request
replays; they are not proof-of-possession after the bearer itself is stolen.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from . import auth
from .database import ProjectAuditEventRecord, ServicePrincipalRecord, ServiceRequestNonceRecord
from .project_auth import (
    PROJECT_ACTIVE, PROJECT_AUDIT_READ, PROJECT_INSPECTION_USE,
    PROJECT_SERVICE_PRINCIPALS_MANAGE, ProjectContext, _project_id,
    _load_project_state, _audit_platform_entry, authorization_error,
    project_not_found_error, require_project_capability, resolve_project_context,
)
from .project_management import _add_project_audit, _record_project_denial, _project_write, _request_id, _timestamp

ALERTS_INGEST = "project.alerts.ingest"
STREAMS_INGEST = "project.streams.ingest"
ALLOWED_CAPABILITIES = frozenset({ALERTS_INGEST, STREAMS_INGEST})
TOKEN_PREFIX = "ay_sp_"
REPLAY_WINDOW_SECONDS = 300
_lock = RLock()
_principals: dict[str, SimpleNamespace] = {}
_nonces: dict[tuple[str, str, str], datetime] = {}


def _now():
    return datetime.now(timezone.utc)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _error(status, code):
    return HTTPException(status_code=status, detail={"code": code, "message": code.replace("_", " ")})


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PrincipalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    displayName: str = Field(min_length=1, max_length=128)
    principalType: str = Field(pattern="^(DEVICE|SERVICE)$")
    capabilities: list[str] = Field(min_length=1, max_length=2)
    expiresAt: datetime

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value):
        if not set(value).issubset(ALLOWED_CAPABILITIES) or len(set(value)) != len(value):
            raise ValueError("only distinct alert-ingest and stream-ingest capabilities are supported")
        return sorted(value)

    @field_validator("displayName")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("displayName cannot be blank")
        return value.strip()

    @field_validator("expiresAt")
    @classmethod
    def validate_expiry(cls, value):
        if value.tzinfo is None:
            raise ValueError("expiresAt must include a timezone")
        if not _now() < value <= _now() + timedelta(days=365):
            raise ValueError("expiresAt must be in the future and within 365 days")
        return value.astimezone(timezone.utc)


class PrincipalPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)
    displayName: str | None = Field(default=None, min_length=1, max_length=128)
    capabilities: list[str] | None = Field(default=None, min_length=1, max_length=2)
    expiresAt: datetime | None = None

    @field_validator("displayName", "capabilities", "expiresAt")
    @classmethod
    def validate_optional(cls, value, info):
        if value is None:
            raise ValueError("omit unchanged fields; null is not supported")
        validator = {"displayName": PrincipalCreate.validate_name,
                     "capabilities": PrincipalCreate.validate_capabilities,
                     "expiresAt": PrincipalCreate.validate_expiry}[info.field_name]
        return validator(value)


class PrincipalRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)


class PrincipalRotate(PrincipalRevision):
    expiresAt: datetime
    _expiry = field_validator("expiresAt")(PrincipalCreate.validate_expiry.__func__)


@dataclass(frozen=True)
class ServicePrincipal:
    service_principal_id: str
    project_id: str
    principal_type: str
    revision: int
    account_id: None = None
    platform_role: None = None
    legacy: bool = False


def _payload(row):
    return {
        "principalId": row.principal_id, "projectId": row.project_id,
        "displayName": row.display_name, "principalType": row.principal_type,
        "capabilities": list(row.capabilities), "revision": row.revision,
        "expiresAt": _timestamp(row.expires_at), "revokedAt": _timestamp(row.revoked_at),
        "lastUsedAt": _timestamp(row.last_used_at), "createdAt": _timestamp(row.created_at),
        "updatedAt": _timestamp(row.updated_at), "createdByAccountId": row.created_by_account_id,
    }


def _new_token(principal_id):
    return f"{TOKEN_PREFIX}{principal_id}.{secrets.token_urlsafe(48)}"


def create_principal(payload, context, request_id):
    if context.lifecycle_state != PROJECT_ACTIVE:
        raise _error(409, "project_not_active")
    principal_id = str(uuid4())
    token = _new_token(principal_id)
    now = _now()
    values = dict(principal_id=principal_id, project_id=context.project_id,
        display_name=payload.displayName, principal_type=payload.principalType,
        capabilities=list(payload.capabilities), credential_digest=_digest(token),
        expires_at=payload.expiresAt, revoked_at=None, last_used_at=None, revision=1,
        created_by_account_id=context.principal.account_id, created_at=now, updated_at=now)
    with _lock:
        if not auth.database.enabled:
            row = SimpleNamespace(**values)
            _principals[principal_id] = row
            _add_project_audit(None, context, request_id, "service_principal.create", "service_principal", principal_id, None, 1, {"capabilities": row.capabilities, "principalType": row.principal_type})
        else:
            with auth.database.session() as session:
                row = ServicePrincipalRecord(**values)
                session.add(row)
                session.flush()
                _add_project_audit(session, context, request_id, "service_principal.create", "service_principal", principal_id, None, 1, {"capabilities": row.capabilities, "principalType": row.principal_type})
    return {**_payload(row), "credential": token, "tokenType": "Bearer"}


def list_principals(project_id):
    with _lock:
        if not auth.database.enabled:
            rows = [row for row in _principals.values() if row.project_id == project_id]
        else:
            with auth.database.session() as session:
                rows = session.scalars(select(ServicePrincipalRecord).where(ServicePrincipalRecord.project_id == project_id)).all()
        return sorted((_payload(row) for row in rows), key=lambda row: row["principalId"])


def mutate_principal(principal_id, payload, context, request_id, action):
    def apply(row, session):
        if row is None or row.project_id != context.project_id:
            raise _error(404, "service_principal_not_found")
        if row.revision != payload.expectedRevision:
            raise _error(409, "revision_conflict")
        if row.revoked_at is not None:
            raise _error(409, "service_principal_revoked")
        if action != "revoke" and context.lifecycle_state != PROJECT_ACTIVE:
            raise _error(409, "project_not_active")
        values = {"revision": row.revision + 1, "updated_at": _now()}
        token = None
        if action == "revoke":
            values["revoked_at"] = _now()
        elif action == "rotate":
            token = _new_token(principal_id)
            values.update(credential_digest=_digest(token), expires_at=payload.expiresAt)
        else:
            for external, internal in [("displayName", "display_name"), ("capabilities", "capabilities"), ("expiresAt", "expires_at")]:
                if external in payload.model_fields_set:
                    values[internal] = getattr(payload, external)
            if len(values) == 2:
                raise _error(422, "empty_patch")
        previous = row.revision
        if session is not None:
            result = session.execute(update(ServicePrincipalRecord).where(
                ServicePrincipalRecord.principal_id == principal_id,
                ServicePrincipalRecord.project_id == context.project_id,
                ServicePrincipalRecord.revision == previous,
            ).values(**values).execution_options(synchronize_session=False))
            if result.rowcount != 1:
                raise _error(409, "revision_conflict")
            session.refresh(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        _add_project_audit(session, context, request_id, f"service_principal.{action}", "service_principal", principal_id, previous, row.revision, {"changedFields": sorted(key for key in values if key != "credential_digest")})
        return {**_payload(row), **({"credential": token, "tokenType": "Bearer"} if token else {})}

    with _lock:
        if not auth.database.enabled:
            return apply(_principals.get(principal_id), None)
        with auth.database.session() as session:
            row = session.scalar(select(ServicePrincipalRecord).where(ServicePrincipalRecord.principal_id == principal_id, ServicePrincipalRecord.project_id == context.project_id).with_for_update())
            return apply(row, session)


def _service_token(scope):
    # No query-string, cookie or legacy-header credentials for machines.
    scheme, _, value = scope.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip().startswith(TOKEN_PREFIX) else None


def _replay_headers(scope):
    stamp = scope.headers.get("x-service-timestamp", "")
    nonce = scope.headers.get("x-service-nonce", "")
    if not re.fullmatch(r"[0-9]{10}", stamp) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce):
        raise _error(401, "service_replay_headers_required")
    requested_at = datetime.fromtimestamp(int(stamp), timezone.utc)
    if abs((_now() - requested_at).total_seconds()) > REPLAY_WINDOW_SECONDS:
        raise _error(401, "service_request_expired")
    return _digest(nonce), requested_at + timedelta(seconds=REPLAY_WINDOW_SECONDS + 1)


def resolve_service_context(scope, capability, *, consume_nonce=True, touch=True):
    if capability not in ALLOWED_CAPABILITIES:
        raise ValueError("unknown service capability")
    token = _service_token(scope) or ""
    principal_id = token[len(TOKEN_PREFIX):].partition(".")[0]
    if len(principal_id) != 36 or len(token) > 180:
        raise auth.authentication_error("service credential")
    requested_project = _project_id(scope, allow_legacy=False)
    request_id = _request_id(scope)
    context = None

    def authorize(row, session):
        nonlocal context
        if row is None or not hmac.compare_digest(row.credential_digest, _digest(token)):
            raise auth.authentication_error("service credential")
        project, _ = _load_project_state(row.project_id, "")
        if project is None:
            raise auth.authentication_error("service credential")
        principal = ServicePrincipal(row.principal_id, row.project_id, row.principal_type, row.revision)
        context = ProjectContext(principal, row.project_id, project.project_code, project.lifecycle_state, None, frozenset(row.capabilities), None, project.revision)
        if row.revoked_at is not None or _utc(row.expires_at) <= _now():
            raise auth.authentication_error("service credential")
        if row.project_id != requested_project:
            raise project_not_found_error()
        if project.lifecycle_state != PROJECT_ACTIVE or capability not in row.capabilities:
            raise authorization_error(capability)
        if consume_nonce:
            nonce_digest, expires_at = _replay_headers(scope)
            if session is None:
                for key in [key for key, expiry in _nonces.items() if expiry < _now()]:
                    del _nonces[key]
                key = (row.project_id, row.principal_id, nonce_digest)
                if key in _nonces:
                    raise _error(409, "service_request_replayed")
                _nonces[key] = expires_at
            else:
                session.execute(delete(ServiceRequestNonceRecord).where(ServiceRequestNonceRecord.expires_at < _now()))
                session.add(ServiceRequestNonceRecord(project_id=row.project_id, principal_id=row.principal_id, nonce_digest=nonce_digest, expires_at=expires_at))
                session.flush()
        if touch:
            row.last_used_at = _now()
        if consume_nonce:
            _add_project_audit(session, context, request_id, "service_principal.use", "service_principal", row.principal_id, row.revision, row.revision, {"capability": capability})
        return context

    try:
        with _lock:
            if not auth.database.enabled:
                return authorize(_principals.get(principal_id), None)
            with auth.database.session() as session:
                row = session.scalar(select(ServicePrincipalRecord).where(ServicePrincipalRecord.principal_id == principal_id).with_for_update())
                return authorize(row, session)
    except IntegrityError as exc:
        failure = _error(409, "service_request_replayed")
        if context is not None:
            _record_project_denial(context, request_id, "service_principal.use", "service_principal", principal_id, failure)
        raise failure from exc
    except HTTPException as exc:
        if context is not None:
            _record_project_denial(context, request_id, "service_principal.use", "service_principal", principal_id, exc)
        raise


def resolve_ingest_context(scope, capability, *, recheck=False):
    if _service_token(scope):
        context = resolve_service_context(scope, capability, consume_nonce=not recheck, touch=not recheck)
        scope.state.project_id = context.project_id
        scope.state.service_principal_id = context.principal.service_principal_id
        return context
    principal = auth.authenticate_websocket(scope) if scope.scope["type"] == "websocket" else auth.authenticate(scope)
    if principal is None or principal.legacy:
        raise auth.authentication_error()
    context = resolve_project_context(principal, _project_id(scope))
    scope.state.project_id = context.project_id
    scope.state.account_id = principal.account_id
    if PROJECT_INSPECTION_USE not in context.capabilities:
        raise authorization_error(PROJECT_INSPECTION_USE)
    if context.platform_entry and not recheck:
        _audit_platform_entry(context, scope, "WEBSOCKET" if scope.scope["type"] == "websocket" else "HTTP")
    return context


async def require_alert_ingest(request: Request):
    return resolve_ingest_context(request, ALERTS_INGEST)


def assert_ingest_envelope(payload, context):
    if payload.projectId is not None and payload.projectId != context.project_id:
        raise _error(409, "project_context_mismatch")
    if isinstance(context.principal, ServicePrincipal):
        if payload.disposition is not None:
            raise authorization_error("project.alerts.dispose")
        if not payload.eventId.startswith(f"service:{context.principal.service_principal_id}:"):
            raise _error(422, "service_event_namespace_required")
        if set(payload.evidence) - {"snapshotDataUrl"}:
            raise _error(422, "service_evidence_upload_required")
    elif payload.eventId.startswith("service:"):
        raise _error(422, "service_event_namespace_reserved")


@contextmanager
def ingest_write_guard(scope):
    # Memory revocation and the write share one lock; persisted event writes
    # also verify the credential revision inside their database transaction.
    with _lock:
        yield resolve_ingest_context(scope, ALERTS_INGEST, recheck=True)


def audit_ingest(context, scope, event_id, *, created=None, error=None):
    if not isinstance(context.principal, ServicePrincipal):
        return
    if error is not None:
        _record_project_denial(context, _request_id(scope), "service_principal.alert_ingest", "service_principal", context.principal.service_principal_id, error)
        return
    changes = {"eventId": event_id, "created": created}
    if not auth.database.enabled:
        _add_project_audit(None, context, _request_id(scope), "service_principal.alert_ingest", "service_principal", context.principal.service_principal_id, None, None, changes)
    else:
        with auth.database.session() as session:
            _add_project_audit(session, context, _request_id(scope), "service_principal.alert_ingest", "service_principal", context.principal.service_principal_id, None, None, changes)


def principal_audits(project_id, principal_id, offset, limit):
    if not auth.database.enabled:
        from .project_management import memory_audits_for_tests
        rows = [row for row in memory_audits_for_tests()["project"]
                if row["projectId"] == project_id and row["targetType"] == "service_principal" and row["targetId"] == principal_id]
        return sorted(rows, key=lambda row: (row["occurredAt"], row["auditId"]), reverse=True)[offset:offset+limit]
    with auth.database.session() as session:
        rows = session.scalars(select(ProjectAuditEventRecord).where(
            ProjectAuditEventRecord.project_id == project_id, ProjectAuditEventRecord.target_type == "service_principal",
            ProjectAuditEventRecord.target_id == principal_id,
        ).order_by(ProjectAuditEventRecord.occurred_at.desc(), ProjectAuditEventRecord.audit_id.desc()).offset(offset).limit(limit)).all()
        return [{"auditId": row.audit_id, "occurredAt": _timestamp(row.occurred_at),
            "requestId": row.request_id, "actorAccountId": row.actor_account_id,
            "actorServicePrincipalId": row.actor_service_principal_id, "projectId": row.project_id,
            "platformRole": row.platform_role, "projectRole": row.project_role,
            "action": row.action, "targetType": row.target_type, "targetId": row.target_id,
            "previousRevision": row.previous_revision, "newRevision": row.new_revision,
            "changeSummary": row.change_summary, "outcome": row.outcome, "failureCode": row.failure_code,
        } for row in rows]


def create_service_principal_router():
    router = APIRouter(prefix="/aiyoloapi/projects/{project_id}/service-principals", tags=["service-principals"])
    manage = require_project_capability(PROJECT_SERVICE_PRINCIPALS_MANAGE)
    read = require_project_capability(PROJECT_AUDIT_READ)

    @router.get("")
    def listing(response: Response, context=Depends(read)):
        response.headers["Cache-Control"] = "no-store"
        return {"projectId": context.project_id, "principals": list_principals(context.project_id)}

    @router.get("/{principal_id}")
    def detail(principal_id: str, response: Response, context=Depends(read)):
        response.headers["Cache-Control"] = "no-store"
        for row in list_principals(context.project_id):
            if row["principalId"] == principal_id:
                return row
        raise _error(404, "service_principal_not_found")

    @router.post("", status_code=201)
    def create(payload: PrincipalCreate, request: Request, response: Response, context=Depends(manage)):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        request_id = _request_id(request)
        return _project_write(context, request_id, "service_principal.create", "service_principal", context.project_id,
            lambda: create_principal(payload, context, request_id))

    @router.get("/{principal_id}/audit")
    def audit(principal_id: str, response: Response, offset: int = Query(default=0, ge=0),
              limit: int = Query(default=100, ge=1, le=200), context=Depends(read)):
        detail(principal_id, response, context)
        return {"projectId": context.project_id, "principalId": principal_id,
                "events": principal_audits(context.project_id, principal_id, offset, limit)}

    def change(principal_id, payload, request, response, context, action):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        request_id = _request_id(request)
        return _project_write(context, request_id, f"service_principal.{action}", "service_principal", principal_id,
            lambda: mutate_principal(principal_id, payload, context, request_id, action))

    @router.patch("/{principal_id}")
    def patch(principal_id: str, payload: PrincipalPatch, request: Request, response: Response, context=Depends(manage)):
        return change(principal_id, payload, request, response, context, "update")

    @router.post("/{principal_id}/rotate")
    def rotate(principal_id: str, payload: PrincipalRotate, request: Request, response: Response, context=Depends(manage)):
        return change(principal_id, payload, request, response, context, "rotate")

    @router.post("/{principal_id}/revoke")
    def revoke(principal_id: str, payload: PrincipalRevision, request: Request, response: Response, context=Depends(read)):
        # Owners/admins retain emergency revocation even for archived projects.
        return change(principal_id, payload, request, response, context, "revoke")

    return router


def reset_memory_service_principals_for_tests():
    with _lock:
        _principals.clear()
        _nonces.clear()
