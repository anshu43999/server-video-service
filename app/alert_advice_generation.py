"""Immutable generation snapshots and idempotent alert-advice API."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .alert_advice_service import AlertAdviceService
from .database import AlertAdviceGenerationRecord
from .project_business import audit_change
from .project_auth import (
    PROJECT_ALERT_ADVICE_GENERATE,
    PROJECT_ALERT_ADVICE_HISTORY_READ,
    PROJECT_ALERT_ADVICE_READ,
    ProjectContext,
    require_project_capability,
)


class GenerationNotFound(KeyError):
    pass


class IdempotencyConflict(ValueError):
    pass


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retryOfGenerationId: str | None = Field(default=None, min_length=1, max_length=128)


def _timestamp(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class AlertAdviceGenerationStore:
    def __init__(self, database=None):
        self.database = database
        self._lock = RLock()
        self._rows: dict[tuple[str, str], dict] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}

    @property
    def persistent(self):
        return self.database is not None and self.database.enabled

    @staticmethod
    def _public(row):
        return deepcopy(row.snapshot)

    @staticmethod
    def _same_request(snapshot, retry_of):
        return snapshot.get("retryOfGenerationId") == retry_of

    def find_idempotent(self, project_id, event_id, key, retry_of):
        if self.persistent:
            with self.database.session() as session:
                row = session.scalar(select(AlertAdviceGenerationRecord).where(
                    AlertAdviceGenerationRecord.project_id == project_id,
                    AlertAdviceGenerationRecord.event_id == event_id,
                    AlertAdviceGenerationRecord.idempotency_key == key,
                ))
                if row is None:
                    return None
                result = self._public(row)
        else:
            generation_id = self._idempotency.get((project_id, event_id, key))
            if generation_id is None:
                return None
            result = deepcopy(self._rows[(project_id, generation_id)])
        if not self._same_request(result, retry_of):
            raise IdempotencyConflict("idempotency key was used with a different request")
        return result

    def create(self, project_id, event_id, requested_by, idempotency_key, retry_of, result, *,
               context=None, request_id=None):
        UUID(idempotency_key)
        with self._lock:
            existing = self.find_idempotent(project_id, event_id, idempotency_key, retry_of)
            if existing is not None:
                return existing, False
            now = datetime.now(timezone.utc)
            snapshot = {
                "contractVersion": "1.0", "generationId": str(uuid4()),
                "projectId": project_id, "eventId": event_id, "requestedBy": requested_by,
                "idempotencyKey": idempotency_key, "retryOfGenerationId": retry_of,
                **deepcopy(result), "createdAt": now.isoformat(), "completedAt": now.isoformat(),
            }
            if self.persistent:
                try:
                    with self.database.session() as session:
                        row = AlertAdviceGenerationRecord(
                            project_id=project_id, generation_id=snapshot["generationId"],
                            event_id=event_id, requested_by=requested_by,
                            idempotency_key=idempotency_key, retry_of_generation_id=retry_of,
                            status=snapshot["status"], snapshot=deepcopy(snapshot),
                            created_at=now, completed_at=now,
                        )
                        session.add(row)
                        session.flush()
                        audit_change(
                            session, context, request_id, "alert_advice_generation.create",
                            "alert_advice_generation", snapshot["generationId"], None,
                            {"generationId": snapshot["generationId"], "eventId": event_id,
                             "status": snapshot["status"],
                             "knowledgeRevision": snapshot.get("knowledgeRevision")},
                        )
                        return deepcopy(snapshot), True
                except IntegrityError:
                    existing = self.find_idempotent(project_id, event_id, idempotency_key, retry_of)
                    if existing is not None:
                        return existing, False
                    raise
            self._rows[(project_id, snapshot["generationId"])] = deepcopy(snapshot)
            self._idempotency[(project_id, event_id, idempotency_key)] = snapshot["generationId"]
            audit_change(
                None, context, request_id, "alert_advice_generation.create",
                "alert_advice_generation", snapshot["generationId"], None,
                {"generationId": snapshot["generationId"], "eventId": event_id,
                 "status": snapshot["status"],
                 "knowledgeRevision": snapshot.get("knowledgeRevision")},
            )
            return deepcopy(snapshot), True

    def get(self, project_id, event_id, generation_id):
        if self.persistent:
            with self.database.session() as session:
                row = session.scalar(select(AlertAdviceGenerationRecord).where(
                    AlertAdviceGenerationRecord.project_id == project_id,
                    AlertAdviceGenerationRecord.event_id == event_id,
                    AlertAdviceGenerationRecord.generation_id == generation_id,
                ))
                if row is None:
                    raise GenerationNotFound(generation_id)
                return self._public(row)
        try:
            row = self._rows[(project_id, generation_id)]
            if row["eventId"] != event_id:
                raise KeyError(generation_id)
            return deepcopy(row)
        except KeyError as exc:
            raise GenerationNotFound(generation_id) from exc

    def list(self, project_id, event_id):
        if self.persistent:
            with self.database.session() as session:
                rows = session.scalars(select(AlertAdviceGenerationRecord).where(
                    AlertAdviceGenerationRecord.project_id == project_id,
                    AlertAdviceGenerationRecord.event_id == event_id,
                ).order_by(AlertAdviceGenerationRecord.created_at.desc(),
                           AlertAdviceGenerationRecord.generation_id.desc())).all()
                return [self._public(row) for row in rows]
        rows = [deepcopy(row) for (pid, _), row in self._rows.items()
                if pid == project_id and row["eventId"] == event_id]
        return sorted(rows, key=lambda row: (row["createdAt"], row["generationId"]), reverse=True)

    def latest(self, project_id, event_id):
        rows = self.list(project_id, event_id)
        if not rows:
            raise GenerationNotFound(event_id)
        return rows[0]


def create_alert_advice_generation_router(store_provider, service_provider, event_store_provider):
    router = APIRouter(prefix="/aiyoloapi/projects/{project_id}/alerts/{event_id}/advice-generations",
                       tags=["alert-advice"])
    generate_capability = require_project_capability(PROJECT_ALERT_ADVICE_GENERATE)
    read_capability = require_project_capability(PROJECT_ALERT_ADVICE_READ)
    history_capability = require_project_capability(PROJECT_ALERT_ADVICE_HISTORY_READ)

    def event(context, event_id):
        try:
            return event_store_provider().get(event_id, context.project_id)
        except KeyError as exc:
            raise HTTPException(404, detail={"code": "EVENT_NOT_FOUND", "message": "alert event was not found"}) from exc

    @router.post("", status_code=201)
    def generate(project_id: str, event_id: str, body: GenerationRequest,
                 request: Request,
                 context: ProjectContext = Depends(generate_capability),
                 idempotency_key: str = Header(alias="Idempotency-Key")):
        try:
            UUID(idempotency_key)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, detail={"code": "IDEMPOTENCY_KEY_INVALID", "message": "a UUID idempotency key is required"}) from exc
        store = store_provider()
        try:
            replay = store.find_idempotent(
                context.project_id, event_id, idempotency_key, body.retryOfGenerationId
            )
        except IdempotencyConflict as exc:
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)}) from exc
        if replay is not None:
            from fastapi.responses import JSONResponse
            return JSONResponse(replay, status_code=200)
        event_snapshot = event(context, event_id)
        if body.retryOfGenerationId is not None:
            try:
                store.get(context.project_id, event_id, body.retryOfGenerationId)
            except GenerationNotFound as exc:
                raise HTTPException(404, detail={"code": "ADVICE_GENERATION_NOT_FOUND", "message": "retry target was not found"}) from exc
        result = service_provider().generate(context.project_id, event_snapshot)
        try:
            snapshot, created = store.create(
                context.project_id, event_id, context.principal.account_id,
                idempotency_key, body.retryOfGenerationId, result, context=context,
                request_id=getattr(request.state, "request_id", None),
            )
        except IdempotencyConflict as exc:
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)}) from exc
        if not created:
            from fastapi.responses import JSONResponse
            return JSONResponse(snapshot, status_code=200)
        return snapshot

    @router.get("/latest")
    def latest(project_id: str, event_id: str, context: ProjectContext = Depends(read_capability)):
        event(context, event_id)
        try:
            return store_provider().latest(context.project_id, event_id)
        except GenerationNotFound as exc:
            raise HTTPException(404, detail={"code": "ADVICE_GENERATION_NOT_FOUND", "message": "no advice generation exists"}) from exc

    @router.get("")
    def history(project_id: str, event_id: str, context: ProjectContext = Depends(history_capability)):
        event(context, event_id)
        return {"generations": store_provider().list(context.project_id, event_id)}

    @router.get("/{generation_id}")
    def detail(project_id: str, event_id: str, generation_id: str,
               context: ProjectContext = Depends(history_capability)):
        event(context, event_id)
        try:
            return store_provider().get(context.project_id, event_id, generation_id)
        except GenerationNotFound as exc:
            raise HTTPException(404, detail={"code": "ADVICE_GENERATION_NOT_FOUND", "message": "advice generation was not found"}) from exc

    return router
