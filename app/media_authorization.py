"""Fail-closed tombstone for old media deployments (ADR-003).

No session lookup, credentials, path parsing, network calls or stream access.
Keeping the callback at 403 also denies leftover pre-upgrade media servers.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class MediaAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=1024)
    token: str = Field(default="", max_length=1024)
    action: str = Field(default="", max_length=32)
    path: str = Field(default="", max_length=256)
    protocol: str = Field(default="", max_length=32)


def authorize_media_read(payload: MediaAuthorizationRequest, streams=None) -> None:
    """Retain the old callable signature; never consult the supplied store."""
    raise HTTPException(status_code=403, detail="live_video_retired")


def create_media_authorization_router():
    router = APIRouter(include_in_schema=False)

    @router.post("/aiyoloapi/internal/media/authorize")
    async def media_authorize():
        # Reject even malformed/empty legacy requests before body validation.
        raise HTTPException(status_code=403, detail="live_video_retired")

    return router
