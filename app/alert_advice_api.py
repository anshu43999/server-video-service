"""Project-scoped simulated alert-advice knowledge management API."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .alert_advice_knowledge import (
    ACTIVE,
    INACTIVE,
    AlertAdviceKnowledgeStore,
    KnowledgeConflict,
    KnowledgeError,
    KnowledgeMatchConflict,
    KnowledgeNotFound,
    normalize_match_key,
)
from .project_auth import (
    PROJECT_ALERT_KNOWLEDGE_MANAGE,
    PROJECT_ALERT_KNOWLEDGE_READ,
    ProjectContext,
    require_project_capability,
    require_platform_capability,
    PLATFORM_ALERT_KNOWLEDGE_MANAGE,
)


class AdviceStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    stepId: str = Field(min_length=1, max_length=128)
    order: StrictInt = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=2000)


class PolicyReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    referenceId: str = Field(min_length=1, max_length=128)
    documentTitle: str = Field(min_length=1, max_length=300)
    documentNumber: str | None = Field(default=None, max_length=128)
    documentVersion: str = Field(min_length=1, max_length=128)
    chapter: str | None = Field(default=None, max_length=300)
    clauseId: str | None = Field(default=None, max_length=128)
    excerpt: str = Field(min_length=1, max_length=5000)
    sourceName: str = Field(min_length=1, max_length=300)
    sourceType: Literal["MOCK_KNOWLEDGE_BASE"] = "MOCK_KNOWLEDGE_BASE"
    effectiveDate: str | None = Field(default=None, max_length=32)


class AdviceTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    steps: list[AdviceStepRequest] = Field(default_factory=list, max_length=50)
    cautions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_steps(self):
        if [step.order for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("step order must be contiguous from one")
        if len({step.stepId for step in self.steps}) != len(self.steps):
            raise ValueError("stepId must be unique")
        if any(not value.strip() for value in self.cautions):
            raise ValueError("cautions must not contain blanks")
        return self


class KnowledgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    riskDescription: str = Field(min_length=1, max_length=2000)
    adviceTemplate: AdviceTemplateRequest
    references: list[PolicyReferenceRequest] = Field(min_length=1, max_length=50)
    applicability: str = Field(min_length=1, max_length=2000)
    sourceType: Literal["MOCK_KNOWLEDGE_BASE"] = "MOCK_KNOWLEDGE_BASE"


class KnowledgeCreate(KnowledgeBody):
    entryId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    alertTypeId: str = Field(min_length=1, max_length=128)
    recognitionCategoryId: str = Field(min_length=1, max_length=128)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"


class KnowledgeReplace(KnowledgeBody):
    expectedRevision: StrictInt = Field(ge=1)


class KnowledgeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ACTIVE", "INACTIVE"]
    expectedRevision: StrictInt = Field(ge=1)


class MatchPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    alertTypeId: str = Field(min_length=1, max_length=128)
    recognitionCategoryId: str = Field(min_length=1, max_length=128)


class BaseUpgrade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=1)
    expectedRevision: StrictInt = Field(ge=1)


class KnowledgeOverride(KnowledgeBody):
    inheritedEntryId: str = Field(min_length=1, max_length=160)
    expectedBaseRevision: StrictInt = Field(ge=1)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"


class KnowledgePublish(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expectedRevision: StrictInt = Field(ge=1)
    notes: str = Field(min_length=1, max_length=2000)


def _payload(body: KnowledgeBody):
    return body.model_dump(exclude={"entryId", "alertTypeId", "recognitionCategoryId", "status", "expectedRevision", "inheritedEntryId", "expectedBaseRevision"})


def _actor(context: ProjectContext):
    return context.principal.account_id


def _request_id(request: Request):
    return getattr(request.state, "request_id", None)


def _raise_store_error(exc):
    if isinstance(exc, KnowledgeNotFound):
        status = 404
    elif isinstance(exc, (KnowledgeConflict, KnowledgeMatchConflict)):
        status = 409
    else:
        status = 422
    raise HTTPException(status, detail={"code": exc.code, "message": str(exc), "retryable": False}) from exc


def create_alert_advice_router(store_provider) -> APIRouter:
    router = APIRouter(prefix="/aiyoloapi/projects/{project_id}/alert-advice", tags=["alert-advice"])
    read = require_project_capability(PROJECT_ALERT_KNOWLEDGE_READ)
    manage = require_project_capability(PROJECT_ALERT_KNOWLEDGE_MANAGE)

    @router.get("/base")
    def project_base(project_id: str, context: ProjectContext = Depends(read)):
        system = store_provider().system
        if system is None:
            raise HTTPException(404, "System knowledge is not configured")
        return {**system.binding(context.project_id), "versions": system.versions()}

    @router.post("/base/upgrade")
    def upgrade_base(project_id: str, body: BaseUpgrade, request: Request, context: ProjectContext = Depends(manage)):
        try:
            return store_provider().system.adopt(context.project_id, body.version, body.expectedRevision, _actor(context), context=context, request_id=_request_id(request))
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.post("/knowledge-overrides", status_code=201)
    def override_entry(project_id: str, body: KnowledgeOverride, request: Request, context: ProjectContext = Depends(manage)):
        try:
            return store_provider().override(context.project_id, body.inheritedEntryId, _payload(body), body.status,
                                             _actor(context), body.expectedBaseRevision, context=context, request_id=_request_id(request))
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.get("/knowledge-entries")
    def list_entries(project_id: str, status: Literal["ACTIVE", "INACTIVE"] | None = None,
                     alertTypeId: str | None = Query(default=None, max_length=128),
                     recognitionCategoryId: str | None = Query(default=None, max_length=128),
                     context: ProjectContext = Depends(read)):
        entries = store_provider().list(context.project_id)
        if status is not None:
            entries = [item for item in entries if item["status"] == status]
        if alertTypeId is not None or recognitionCategoryId is not None:
            if alertTypeId is None or recognitionCategoryId is None:
                raise HTTPException(422, detail={"code": "MATCH_KEY_INVALID", "message": "both match fields are required"})
            key = normalize_match_key(alertTypeId, recognitionCategoryId)
            entries = [item for item in entries if (item["matchKey"]["alertTypeId"], item["matchKey"]["recognitionCategoryId"]) == key]
        return {"entries": entries}

    @router.post("/knowledge-entries", status_code=201)
    def create_entry(project_id: str, body: KnowledgeCreate, request: Request,
                     context: ProjectContext = Depends(manage), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        try:
            item = store_provider().create(
                context.project_id, body.entryId, body.alertTypeId, body.recognitionCategoryId,
                _payload(body), _actor(context), status=body.status, context=context,
                request_id=idempotency_key or _request_id(request),
            )
            return item
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.post("/knowledge-entries/match-preview")
    def preview(project_id: str, body: MatchPreview, context: ProjectContext = Depends(read)):
        key = normalize_match_key(body.alertTypeId, body.recognitionCategoryId)
        matched = store_provider().find_active_exact(context.project_id, *key)
        return {"matchKey": {"alertTypeId": key[0], "recognitionCategoryId": key[1]},
                "matched": matched is not None, "entry": matched}

    @router.get("/knowledge-entries/{entry_id}")
    def get_entry(project_id: str, entry_id: str, context: ProjectContext = Depends(read)):
        try:
            return store_provider().get(context.project_id, entry_id)
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.put("/knowledge-entries/{entry_id}")
    def replace_entry(project_id: str, entry_id: str, body: KnowledgeReplace, request: Request,
                      context: ProjectContext = Depends(manage), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        try:
            return store_provider().replace(
                context.project_id, entry_id, _payload(body), _actor(context), body.expectedRevision,
                context=context, request_id=idempotency_key or _request_id(request),
            )
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.post("/knowledge-entries/{entry_id}/status")
    def set_entry_status(project_id: str, entry_id: str, body: KnowledgeStatus, request: Request,
                         context: ProjectContext = Depends(manage), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        try:
            return store_provider().set_status(
                context.project_id, entry_id, body.status, _actor(context), body.expectedRevision,
                context=context, request_id=idempotency_key or _request_id(request),
            )
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.get("/knowledge-entries/{entry_id}/revisions")
    def revisions(project_id: str, entry_id: str, context: ProjectContext = Depends(read)):
        try:
            return {"revisions": store_provider().revisions(context.project_id, entry_id)}
        except KnowledgeError as exc:
            _raise_store_error(exc)

    return router


def create_system_alert_knowledge_router(store_provider):
    router = APIRouter(prefix="/aiyoloapi/platform/alert-advice", tags=["system-alert-knowledge"])
    manage = require_platform_capability(PLATFORM_ALERT_KNOWLEDGE_MANAGE)

    @router.get("/knowledge-entries")
    def catalog(principal=Depends(manage)):
        value = store_provider().system.catalog()
        return {"entries": value["entries"], "revision": value["revision"]}

    @router.get("/versions")
    def versions(principal=Depends(manage)):
        return {"versions": store_provider().system.versions()}

    @router.get("/versions/{version}")
    def release(version: int, principal=Depends(manage)):
        try:
            return store_provider().system.release(version)
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.get("/knowledge-entries/{entry_id}")
    def get(entry_id: str, principal=Depends(manage)):
        item = next((item for item in store_provider().system.catalog()["entries"] if item["entryId"] == entry_id), None)
        if item is None:
            _raise_store_error(KnowledgeNotFound("system entry was not found"))
        return item

    @router.post("/publish", status_code=201)
    def publish(body: KnowledgePublish, request: Request, principal=Depends(manage)):
        try:
            return store_provider().system.publish(body.expectedRevision, body.notes, principal.account_id, context=principal, request_id=_request_id(request))
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.post("/knowledge-entries", status_code=201)
    def create(body: KnowledgeCreate, request: Request, principal=Depends(manage)):
        try:
            return store_provider().system.mutate("create", principal.account_id, entry_id=body.entryId, alert_type_id=body.alertTypeId,
                                                 recognition_category_id=body.recognitionCategoryId, payload=_payload(body), status=body.status,
                                                 context=principal, request_id=_request_id(request))
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.put("/knowledge-entries/{entry_id}")
    def replace(entry_id: str, body: KnowledgeReplace, request: Request, principal=Depends(manage)):
        try:
            return store_provider().system.mutate("replace", principal.account_id, entry_id=entry_id, payload=_payload(body), expected_revision=body.expectedRevision,
                                                 context=principal, request_id=_request_id(request))
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.post("/knowledge-entries/{entry_id}/status")
    def status(entry_id: str, body: KnowledgeStatus, request: Request, principal=Depends(manage)):
        try:
            return store_provider().system.mutate("set_status", principal.account_id, entry_id=entry_id, status=body.status, expected_revision=body.expectedRevision,
                                                 context=principal, request_id=_request_id(request))
        except KnowledgeError as exc:
            _raise_store_error(exc)

    @router.get("/knowledge-entries/{entry_id}/revisions")
    def revisions(entry_id: str, principal=Depends(manage)):
        result = store_provider().system.catalog()["history"].get(entry_id)
        if result is None:
            _raise_store_error(KnowledgeNotFound("system entry was not found"))
        return {"revisions": result}

    @router.post("/knowledge-entries/match-preview")
    def preview(body: MatchPreview, principal=Depends(manage)):
        key = dict(zip(("alertTypeId", "recognitionCategoryId"), normalize_match_key(body.alertTypeId, body.recognitionCategoryId)))
        item = next((item for item in store_provider().system.catalog()["entries"] if item["matchKey"] == key and item["status"] == ACTIVE), None)
        return {"matchKey": key, "matched": item is not None, "entry": item}

    return router
