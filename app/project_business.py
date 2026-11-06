"""Shared transaction boundaries for project business configuration."""
from __future__ import annotations

from sqlalchemy import select

from .database import ProjectRecord, ProjectModelAssignmentRecord
from .project_management import _add_project_audit, _add_platform_audit
from fastapi import HTTPException
from functools import wraps
from copy import deepcopy


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


_memory_model_assignments: dict[tuple, dict] = {}


def model_assignments(database_manager, project_id: str, model_id: str) -> list[dict]:
    if database_manager is not None and database_manager.enabled:
        with database_manager.session() as session:
            rows = session.scalars(select(ProjectModelAssignmentRecord).where(
                ProjectModelAssignmentRecord.project_id == project_id,
                ProjectModelAssignmentRecord.model_id == model_id,
                ProjectModelAssignmentRecord.enabled.is_(True),
            )).all()
            return [{"modelId": row.model_id, "modelVersion": row.model_version} for row in rows]
    return [dict(value) for key, value in _memory_model_assignments.items()
            if key[0] == project_id and value.get("modelId") == model_id and value.get("enabled")]


def lock_project(session, project_id: str, *, enforce_lifecycle: bool = True) -> None:
    """Serialize first inserts as well as updates on PostgreSQL."""
    row = session.scalar(select(ProjectRecord).where(
        ProjectRecord.project_id == project_id
    ).with_for_update())
    if enforce_lifecycle and row is not None and row.lifecycle_state == "ARCHIVED":
        raise HTTPException(403, detail={"code": "project_read_only", "message": "archived projects are read-only"})


def audit_change(session, context, request_id: str | None, action: str,
                 target_type: str, target_id: str, before, after) -> None:
    if context is None:
        return
    from uuid import uuid4
    writer = _add_project_audit if hasattr(context, "project_id") else _add_platform_audit
    writer(
        session, context, request_id or str(uuid4()), action, target_type, target_id,
        (before or {}).get("revision", (before or {}).get("ruleVersion")),
        (after or {}).get("revision", (after or {}).get("ruleVersion")),
        {"before": deepcopy(before), "after": deepcopy(after)},
    )
