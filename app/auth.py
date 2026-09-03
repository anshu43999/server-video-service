from fastapi import Header, HTTPException, status

from .config import settings


def _check_token(expected: str | None, provided: str | None, scope: str) -> None:
    if expected and provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": f"valid {scope} token required"},
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    _check_token(settings.admin_token, x_admin_token, "admin")


async def require_mobile(x_video_service_token: str | None = Header(default=None, alias="X-Video-Service-Token")) -> None:
    _check_token(settings.mobile_token, x_video_service_token, "mobile")
