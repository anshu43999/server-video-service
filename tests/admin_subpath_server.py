"""Local-only proxy fixture: strip /video and rewrite HTML like production.

Uses isolated in-memory authentication/business fixtures, never app.main or
production database configuration. Other root paths deliberately reject access.
"""
import argparse
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn
from fastapi import FastAPI
from starlette.responses import JSONResponse

from app import auth, config
from app.admin_frontend import mount_admin_frontend
from app.config import Settings
from app.database import DatabaseManager


def create_app():
    # Only real auth/project handlers are needed for routing: no model catalog,
    # app.main, lifespan workers, disk data or external database is loaded.
    auth.database = DatabaseManager(None)
    auth.settings = Settings(_env_file=None, database_url=None, admin_token=None, mobile_token=None)
    config.settings = auth.settings
    importlib.import_module("app.database").database = auth.database
    from app.project_management import create_project_management_router, _create_project, ProjectCreateRequest
    admin = auth._create_account("cutover-admin", "cutover-test-password", auth.ROLE_ADMIN)
    owner = auth._create_account("cutover-owner", "cutover-test-password", auth.ROLE_OPERATOR)
    _create_project(ProjectCreateRequest(projectCode="cutover-project", displayName="验收项目",
                                         ownerAccountId=owner.account_id), admin, "subpath-browser-fixture")
    app = FastAPI()
    app.include_router(auth.create_auth_router())
    app.include_router(create_project_management_router())
    mount_admin_frontend(app, mode="vue", build_dir=ROOT / "admin-web/dist",
                         preview_dir=ROOT / "admin-web/dist-preview")
    return app


class SubpathProxy:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path.startswith("/aiyoloapi/"):
            return await self.app(scope, receive, send)
        if not path.startswith("/video/"):
            return await JSONResponse({"other_project": True}, status_code=401)(scope, receive, send)
        upstream = dict(scope, path=path[len("/video"):], root_path="")
        upstream["raw_path"] = upstream["path"].encode()
        messages = []

        async def collect(message):
            messages.append(message)

        await self.app(upstream, receive, collect)
        start = messages[0]
        content_type = dict(start["headers"]).get(b"content-type", b"")
        body = b"".join(m.get("body", b"") for m in messages[1:])
        if content_type.startswith(b"text/html"):
            body = body.replace(b'="/admin/', b'="/video/admin/')
        start["headers"] = [(k, v) for k, v in start["headers"] if k != b"content-length"]
        start["headers"].append((b"content-length", str(len(body)).encode()))
        await send(start)
        await send({"type": "http.response.body", "body": body})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4175)
    parser.add_argument("--direct", action="store_true")
    args = parser.parse_args()
    app = create_app()
    uvicorn.run(app if args.direct else SubpathProxy(app), host="127.0.0.1", port=args.port, log_level="warning")
