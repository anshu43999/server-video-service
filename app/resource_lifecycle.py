"""Shared lifecycle preconditions; no network channel and no remote device wipe."""
from copy import deepcopy
from hashlib import sha256
import json
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from .database import (ResourceLifecycleOperationRecord, ResourceLifecycleEventRecord)


def reject(code, message, status=409):
    raise HTTPException(status, detail={"code": code, "message": message})


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def deletion_headers(request, *, allow_body=False):
    match, key = request.headers.get("if-match"), request.headers.get("idempotency-key")
    if match is None or key is None:
        reject("deletion_precondition_required", "If-Match and Idempotency-Key are required", 428)
    if not re.fullmatch('"[1-9][0-9]{0,17}"', match) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
        reject("deletion_precondition_invalid", "expected quoted revision and bounded idempotency key", 400)
    if not allow_body and (request.headers.get("content-length", "0") != "0" or "transfer-encoding" in request.headers):
        reject("deletion_body_not_supported", "deletion does not support a body or cascade options", 400)
    return int(match[1:-1]), key


def guard_stream_write(session, model_id, version):
    if model_id is None:
        return
    pending = session.scalars(select(ResourceLifecycleOperationRecord).where(
        ResourceLifecycleOperationRecord.scope_key.like("model:%"),
        ResourceLifecycleOperationRecord.stage != "aborted"))
    for operation in pending:
        payload = operation.payload
        if payload.get("modelId") == model_id and (version is None or payload.get("version") == version):
            if payload.get("action") == "remove" or operation.stage != "confirmed":
                reject("model_removal_in_progress", "model release cannot accept new stream references")


def operation_identity(actor, scope, key, expected):
    return digest([actor, scope, key]), digest([scope, expected])


def add_event(session, scope, revision, payload, operation_id=None):
    if session is not None:
        from .model_updates.events import add_domain_event
        add_domain_event(session, scope.split(':', 1)[-1].split('/', 1)[0] if scope.startswith('scene:') else '*',
                         'lifecycle', {'scope': scope, 'revision': revision})
        session.add(ResourceLifecycleEventRecord(event_id=str(uuid4()), scope_key=scope,
            lifecycle_revision=revision, payload=deepcopy(payload), operation_id=operation_id))


def guard_model_write(session, catalog, model_id, version):
    """Call inside the SAME default-project lock used by deletion preparation."""
    scope = f"model:{model_id}@{version}"
    if session is not None:
        for operation in session.scalars(select(ResourceLifecycleOperationRecord).where(
                ResourceLifecycleOperationRecord.scope_key == scope,
                ResourceLifecycleOperationRecord.stage != "aborted")):
            if operation.payload.get("action") == "remove" or operation.stage != "confirmed":
                reject("model_removal_in_progress", "release is being removed or has been removed")
    registry = catalog._load()
    if not isinstance(registry, dict):
        return  # Test doubles are not a production catalog.
    if any(item.get("modelId") == model_id and item.get("version") == version
           and item.get("status") == "UNINSTALLED" for item in registry.get("modelHistory", [])):
        reject("model_removed", "release identity is retired and cannot be reused")
    if any(item.get("scope") == scope and item.get("stage") != "aborted"
           and (item.get("intent", {}).get("action") == "remove" or item.get("stage") != "confirmed")
           for item in registry.get("lifecycleRequests", {}).values()):
        reject("model_removal_in_progress", "release is being removed or has been removed")
