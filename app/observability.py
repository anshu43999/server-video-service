"""Allowlisted request telemetry. Never log URLs, headers, bodies or exceptions."""
import json
import logging
import time
from uuid import uuid4

logger = logging.getLogger("aiyolo.requests")


class SafeAccessFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn's default access line includes the raw query string. The
        # structured middleware below is the authoritative request log instead.
        return False


class SafeWebSocketFilter(logging.Filter):
    def filter(self, record):
        if 'WebSocket' in str(record.msg):
            record.msg, record.args = 'WebSocket transport event (see correlated request telemetry)', ()
        return True


class RequestTelemetry:
    def __init__(self, app):
        self.app = app
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler())
        access = logging.getLogger("uvicorn.access")
        if not any(isinstance(f, SafeAccessFilter) for f in access.filters):
            access.addFilter(SafeAccessFilter())
        transport = logging.getLogger('uvicorn.error')
        if not any(isinstance(f, SafeWebSocketFilter) for f in transport.filters):
            transport.addFilter(SafeWebSocketFilter())

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        started = time.monotonic()
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        # All existing audit writers now receive the same server-generated ID.
        scope["headers"] = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"x-request-id"] + [(b"x-request-id", request_id.encode())]
        status, completed = 500, False

        async def safe_send(message):
            nonlocal status, completed
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"] + [(b"x-request-id", request_id.encode())]
                if scope.get("state", {}).get("legacy_project_mapping"):
                    message["headers"] += [
                        (b"warning", b'299 - "Legacy default-project mapping; send explicit project context"'),
                        (b"sunset", scope["state"]["legacy_project_until"].encode("ascii")),
                    ]
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True
            elif message["type"] == "websocket.accept":
                status = 101
            elif message["type"] == "websocket.close":
                status, completed = message.get("code", 1000), True
            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        finally:
            state = scope.get("state", {})
            route = getattr(scope.get("route"), "path", "unmatched")
            logger.info(json.dumps({
                "event": "request.finished", "requestId": request_id,
                "accountId": state.get("account_id"), "projectId": state.get("project_id"),
                "servicePrincipalId": state.get("service_principal_id"),
                "transport": scope["type"], "route": route, "status": status,
                "completed": completed, "durationMs": round((time.monotonic() - started) * 1000, 2),
            }, separators=(",", ":")))
