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


async def require_catalog_access(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    x_video_service_token: str | None = Header(default=None, alias="X-Video-Service-Token"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """Authorize model catalog reads for either an admin or mobile client.

    The marketplace is consumed by the Android client, while the admin UI also
    needs to inspect it.  When either token is configured, at least one matching
    credential is required.  Bearer authorization is accepted for admin tooling
    in addition to the legacy ``X-Admin-Token`` header.
    """
    bearer = None
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            bearer = value
    if not settings.admin_token and not settings.mobile_token:
        return
    if settings.admin_token and (x_admin_token == settings.admin_token or bearer == settings.admin_token):
        return
    if settings.mobile_token and x_video_service_token == settings.mobile_token:
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "authentication_required", "message": "valid catalog token required"},
        headers={"WWW-Authenticate": "Bearer"},
    )
