from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .config import settings
from .database import AccountRecord, AccountSessionRecord, database


ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
SESSION_COOKIE = "aiyolo_session"
PASSWORD_ITERATIONS = 310_000


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: str
    legacy: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


class AuthRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)


class CreateUserRequest(AuthRequest):
    role: str = Field(default=ROLE_OPERATOR, pattern="^(admin|operator)$")


_memory_lock = RLock()
_memory_accounts: dict[str, tuple[str, str, bool]] = {}
_memory_sessions: dict[str, tuple[str, str, datetime]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_ttl() -> timedelta:
    return timedelta(days=max(1, min(int(settings.auth_session_days), 365)))


def _normalise_username(value: str) -> str:
    username = value.strip().lower()
    if not username or any(character.isspace() for character in username):
        raise HTTPException(
            status_code=422,
            detail={"code": "username_invalid", "message": "用户名不能包含空白字符"},
        )
    return username


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii")
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${encode(salt)}${encode(digest)}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.urlsafe_b64decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


def _session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _account_count() -> int:
    if not database.enabled:
        with _memory_lock:
            return len(_memory_accounts)
    with database.session() as session:
        return int(session.scalar(select(func.count()).select_from(AccountRecord)) or 0)


def accounts_configured() -> bool:
    try:
        return _account_count() > 0
    except Exception:
        return False


def _create_account(username: str, password: str, role: str) -> CurrentUser:
    username = _normalise_username(username)
    if role not in {ROLE_ADMIN, ROLE_OPERATOR}:
        raise HTTPException(status_code=422, detail={"code": "role_invalid", "message": "角色无效"})
    password_hash = _hash_password(password)
    if not database.enabled:
        with _memory_lock:
            if username in _memory_accounts:
                raise HTTPException(status_code=409, detail={"code": "username_exists", "message": "用户名已存在"})
            _memory_accounts[username] = (password_hash, role, True)
        return CurrentUser(username, role)
    with database.session() as session:
        if session.get(AccountRecord, username) is not None:
            raise HTTPException(status_code=409, detail={"code": "username_exists", "message": "用户名已存在"})
        session.add(AccountRecord(username=username, password_hash=password_hash, role=role, enabled=True))
    return CurrentUser(username, role)


def _issue_session(user: CurrentUser) -> str:
    token = secrets.token_urlsafe(48)
    expires_at = _now() + _session_ttl()
    if not database.enabled:
        with _memory_lock:
            _memory_sessions[_session_hash(token)] = (user.username, user.role, expires_at)
        return token
    with database.session() as session:
        session.add(
            AccountSessionRecord(
                session_hash=_session_hash(token),
                username=user.username,
                role=user.role,
                expires_at=expires_at,
            )
        )
    return token


def _session_user(token: str | None) -> CurrentUser | None:
    if not token or len(token) < 24:
        return None
    digest = _session_hash(token)
    now = _now()
    if not database.enabled:
        with _memory_lock:
            value = _memory_sessions.get(digest)
            if not value:
                return None
            username, role, expires_at = value
            if expires_at <= now:
                _memory_sessions.pop(digest, None)
                return None
            return CurrentUser(username, role)
    with database.session() as session:
        record = session.scalar(
            select(AccountSessionRecord).where(
                AccountSessionRecord.session_hash == digest,
                AccountSessionRecord.revoked_at.is_(None),
                AccountSessionRecord.expires_at > now,
            )
        )
        if record is None:
            return None
        account = session.get(AccountRecord, record.username)
        if account is None or not account.enabled:
            return None
        return CurrentUser(account.username, account.role)


def _credential(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return (
        request.cookies.get(SESSION_COOKIE)
        or request.headers.get("x-admin-token")
        or request.headers.get("x-video-service-token")
    )


def _legacy_user(request, required_role: str | None) -> CurrentUser | None:
    admin = request.headers.get("x-admin-token")
    mobile = request.headers.get("x-video-service-token")
    authorization = request.headers.get("authorization", "")
    scheme, _, bearer = authorization.partition(" ")
    if settings.admin_token and (
        admin == settings.admin_token or (scheme.lower() == "bearer" and bearer == settings.admin_token)
    ):
        return CurrentUser("legacy-admin", ROLE_ADMIN, legacy=True) if required_role in {None, ROLE_ADMIN} else None
    if settings.mobile_token and mobile == settings.mobile_token:
        return CurrentUser("legacy-mobile", ROLE_OPERATOR, legacy=True) if required_role in {None, ROLE_OPERATOR} else None
    return None


def authentication_error(scope: str = "account session") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "authentication_required", "message": f"valid {scope} required"},
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate(request: Request, required_role: str | None = None) -> CurrentUser | None:
    user = _session_user(_credential(request))
    if user is not None and (required_role is None or user.role == required_role or user.is_admin):
        return user
    legacy = _legacy_user(request, required_role)
    if legacy is not None:
        return legacy
    return None


async def require_admin(request: Request) -> CurrentUser:
    user = authenticate(request, ROLE_ADMIN)
    if user is None:
        raise authentication_error("administrator session")
    return user


async def require_mobile(request: Request) -> CurrentUser:
    user = authenticate(request, ROLE_OPERATOR)
    if user is None:
        raise authentication_error("mobile session")
    return user


async def require_catalog_access(request: Request) -> CurrentUser:
    user = authenticate(request)
    if user is None:
        raise authentication_error("catalog session")
    return user


def authenticate_websocket(websocket, required_role: str | None = None) -> CurrentUser | None:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, bearer = authorization.partition(" ")
    credential = bearer.strip() if scheme.lower() == "bearer" else websocket.cookies.get(SESSION_COOKIE)
    credential = credential or websocket.headers.get("x-admin-token") or websocket.headers.get("x-video-service-token")
    user = _session_user(credential)
    if user is not None and (required_role is None or user.role == required_role or user.is_admin):
        return user
    request_like = type("WebSocketRequest", (), {"headers": websocket.headers, "cookies": websocket.cookies})()
    legacy = _legacy_user(request_like, required_role)
    if legacy is not None:
        return legacy
    return None


def revoke_session(token: str | None) -> None:
    if not token:
        return
    digest = _session_hash(token)
    if not database.enabled:
        with _memory_lock:
            _memory_sessions.pop(digest, None)
        return
    with database.session() as session:
        record = session.get(AccountSessionRecord, digest)
        if record is not None:
            record.revoked_at = _now()


def _login(username: str, password: str) -> tuple[CurrentUser, str]:
    username = _normalise_username(username)
    record = None
    if not database.enabled:
        with _memory_lock:
            record = _memory_accounts.get(username)
    else:
        with database.session() as session:
            account = session.get(AccountRecord, username)
            if account is not None:
                record = (account.password_hash, account.role, account.enabled)
    if record is None or not record[2] or not _verify_password(password, record[0]):
        raise HTTPException(status_code=401, detail={"code": "login_failed", "message": "用户名或密码错误"})
    user = CurrentUser(username, record[1])
    return user, _issue_session(user)


def _auth_response(response: Response, user: CurrentUser, token: str) -> dict:
    ttl_seconds = int(_session_ttl().total_seconds())
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=ttl_seconds)
    return {
        "accessToken": token,
        "tokenType": "Bearer",
        "expiresIn": ttl_seconds,
        "user": {"username": user.username, "role": user.role},
    }


def create_auth_router() -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.get("/status")
    async def auth_status(request: Request):
        user = authenticate(request)
        return {
            "setupRequired": not accounts_configured(),
            "authenticated": user is not None and not user.legacy,
            "user": {"username": user.username, "role": user.role} if user and not user.legacy else None,
        }

    @router.post("/setup")
    async def auth_setup(payload: AuthRequest, response: Response):
        if accounts_configured():
            raise HTTPException(status_code=409, detail={"code": "setup_complete", "message": "首个管理员已创建"})
        user = _create_account(payload.username, payload.password, ROLE_ADMIN)
        return _auth_response(response, user, _issue_session(user))

    @router.post("/login")
    async def auth_login(payload: AuthRequest, response: Response):
        user, token = _login(payload.username, payload.password)
        return _auth_response(response, user, token)

    @router.get("/me")
    async def auth_me(request: Request):
        user = authenticate(request)
        if user is None or user.legacy:
            raise authentication_error()
        return {"username": user.username, "role": user.role}

    @router.post("/logout")
    async def auth_logout(request: Request, response: Response):
        revoke_session(_credential(request))
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @router.get("/users")
    async def auth_users(request: Request):
        user = authenticate(request, ROLE_ADMIN)
        if user is None:
            raise authentication_error("administrator session")
        if not database.enabled:
            with _memory_lock:
                rows = [
                    {"username": name, "role": values[1], "enabled": values[2]}
                    for name, values in _memory_accounts.items()
                ]
        else:
            with database.session() as session:
                rows = [
                    {"username": row.username, "role": row.role, "enabled": row.enabled}
                    for row in session.scalars(select(AccountRecord)).all()
                ]
        return {"users": rows}

    @router.post("/users")
    async def auth_create_user(payload: CreateUserRequest, request: Request):
        user = authenticate(request, ROLE_ADMIN)
        if user is None:
            raise authentication_error("administrator session")
        created = _create_account(payload.username, payload.password, payload.role)
        return {"username": created.username, "role": created.role, "enabled": True}

    return router


def reset_memory_auth_for_tests() -> None:
    with _memory_lock:
        _memory_accounts.clear()
        _memory_sessions.clear()
