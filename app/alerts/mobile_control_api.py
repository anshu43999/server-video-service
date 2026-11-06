"""Project-scoped backend requests and original-capture reconciliation."""
import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ..project_auth import (PROJECT_ALERTS_DISPOSE, PROJECT_ALERTS_READ,
                            PROJECT_INSPECTION_USE, ProjectContext, require_project_capability)
from .disposition import public_alert_event


class CaptureIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    eventId: str = Field(min_length=1, max_length=256)
    producerId: UUID


class CaptureSync(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[CaptureIdentity] = Field(max_length=100)


class OriginalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operationId: UUID
    expectedRevision: StrictInt = Field(ge=0)


class OriginalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producerId: UUID
    status: Literal["UPLOADED", "UNAVAILABLE"]
    contentVersion: StrictInt | None = Field(default=None, ge=1)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason: Literal["no_local_capture", "local_file_missing", "local_media_purged", "invalid_local_evidence"] | None = None

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "UPLOADED":
            if self.contentVersion is None or self.sha256 is None or self.reason is not None:
                raise ValueError("uploaded receipt requires version/digest only")
        elif self.reason is None or self.contentVersion is not None or self.sha256 is not None:
            raise ValueError("unavailable receipt requires reason only")
        return self


def control_error(error):
    if isinstance(error, KeyError):
        return HTTPException(404, detail={"code": "event_not_found", "retryable": False})
    code = str(error)
    return HTTPException(409 if code != "not_mobile_capture" else 422,
                         detail={"code": code, "message": code, "retryable": code == "original_not_uploaded"})


def create_mobile_control_router(store):
    router = APIRouter(prefix="/aiyoloapi/projects/{project_id}/alerts")

    @router.post("/mobile-sync", dependencies=[Depends(require_project_capability(PROJECT_INSPECTION_USE))])
    def sync(project_id: str, body: CaptureSync,
             context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_READ))):
        return {"events": store.mobile_sync(context.project_id, context.principal.account_id,
                                           [item.model_dump(mode="json") for item in body.events])}

    @router.post("/{event_id}/original-requests")
    def request_original(project_id: str, event_id: str, body: OriginalRequest, request: Request,
                         context: ProjectContext = Depends(require_project_capability(PROJECT_ALERTS_DISPOSE))):
        if request.headers.get("Idempotency-Key") != str(body.operationId):
            raise HTTPException(422, detail={"code": "idempotency_key_mismatch"})
        digest = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        try:
            return public_alert_event(store.request_original(event_id, context.project_id,
                context.principal.account_id, body.expectedRevision, str(body.operationId), digest))
        except (ValueError, KeyError) as error:
            raise control_error(error) from error

    @router.post("/{event_id}/original-requests/{request_id}/receipt")
    def receipt(project_id: str, event_id: str, request_id: UUID, body: OriginalReceipt,
                context: ProjectContext = Depends(require_project_capability(PROJECT_INSPECTION_USE))):
        try:
            return store.original_receipt(event_id, context.project_id, context.principal.account_id,
                                          str(request_id), body.model_dump(mode="json"))
        except (ValueError, KeyError) as error:
            raise control_error(error) from error

    return router
