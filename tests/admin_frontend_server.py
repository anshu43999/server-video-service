"""Local-only browser fixture: production hosting and real in-memory cookie auth.

Auth and management use the unmodified routers. The business fixture mounts
real handlers with an isolated temporary catalog, without background workers,
external providers or a database. Older page fixtures still intercept responses.
"""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
import uvicorn

from app import auth
from app.admin_frontend import mount_admin_frontend
from app.config import Settings
from app.database import DatabaseManager
from app.project_management import create_project_management_router, _create_project, ProjectCreateRequest


def create_app(mode: str) -> FastAPI:
    auth.database = DatabaseManager(None)
    auth.settings = Settings(_env_file=None, database_url=None, admin_token=None, mobile_token=None)
    admin = auth._create_account('cutover-admin', 'cutover-test-password', auth.ROLE_ADMIN)
    auth._create_account('cutover-operator', 'cutover-test-password', auth.ROLE_OPERATOR)
    owner = auth._create_account('cutover-owner', 'cutover-test-password', auth.ROLE_OPERATOR)
    _create_project(ProjectCreateRequest(projectCode='cutover-project', displayName='验收项目', ownerAccountId=owner.account_id), admin, 'browser-fixture')
    app = FastAPI()
    from app.observability import RequestTelemetry
    app.add_middleware(RequestTelemetry)
    app.include_router(auth.create_auth_router())
    app.include_router(create_project_management_router())

    @app.get('/', include_in_schema=False)
    def root():
        return RedirectResponse('/admin/', status_code=307)

    @app.get('/aiyoloapi/rules', dependencies=[Depends(auth.require_admin)])
    def rules():
        return {'rules': []}

    @app.get('/aiyoloapi/rules/audit', dependencies=[Depends(auth.require_admin)])
    def audit():
        return {'audit': []}

    @app.get('/aiyoloapi/capabilities/sources', dependencies=[Depends(auth.require_admin)])
    def sources():
        return {'sources': []}

    from admin_business_fixture import mount_business
    mount_business(app, admin)
    mount_admin_frontend(app, mode=mode,
                         build_dir=ROOT / 'admin-web/dist', preview_dir=ROOT / 'admin-web/dist-preview')
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['vue'], default='vue')
    parser.add_argument('--port', type=int, default=4174)
    args = parser.parse_args()
    uvicorn.run(create_app(args.mode), host='127.0.0.1', port=args.port, log_level='warning')
