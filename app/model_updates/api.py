"""Exact account-level endpoints; existing project download scopes are unchanged."""
import json
import logging
import time
from functools import wraps

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from .. import auth
from ..project_auth import resolve_project_context, PROJECT_MODELS_ASSIGN, _audit_platform_entry
from .models import Device, Inbox
from .protocol import UpdateError, PAGE_BYTES, now, timestamp, utc, response, validate


class UpdateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def handle(request):
            started = time.monotonic()
            try:
                result = await handler(request)
            except UpdateError as exc:
                result = JSONResponse(exc.payload(), status_code=exc.status,
                    headers={'Retry-After': str(exc.retry_after)} if exc.retry_after else {})
            except SQLAlchemyError:
                error = UpdateError(503, 'temporarily_unavailable')
                result = JSONResponse(error.payload(), status_code=503)
            service = getattr(request.state, 'model_update_service', None)
            if service is not None:
                try:
                    await run_in_threadpool(service.store.observe, 'control_http_' + str(result.status_code),
                                            time.monotonic() - started)
                except SQLAlchemyError:
                    logging.getLogger(__name__).warning('model update observation unavailable')
            return result
        return handle


async def read_body(request, maximum):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise UpdateError(413, 'capacity_exceeded')
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate key')
                result[key] = value
            return result
        value = json.loads(body.decode('utf-8'), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        if not isinstance(value, dict):
            raise ValueError('object expected')
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise UpdateError(400, 'invalid_request') from None


def query(request, allowed):
    if set(request.query_params) - set(allowed) or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise UpdateError(400, 'invalid_request')
    try:
        limit = int(request.query_params.get('limit', '100'))
        if not 1 <= limit <= 200:
            raise ValueError()
    except ValueError:
        raise UpdateError(400, 'invalid_request') from None
    return limit


def create_router(service_provider):
    router = APIRouter(route_class=UpdateRoute)

    def authenticated(request):
        principal = auth.authenticate(request)
        if principal is None or principal.legacy:
            raise UpdateError(401, 'login_required')
        request.state.account_id = principal.account_id
        return principal

    async def identity(request, key=None, principal=None):
        principal = principal or authenticated(request)
        service = service_provider()
        request.state.model_update_service = service
        await run_in_threadpool(service.store.rate_limit, key or principal.account_id)
        return principal, service

    @router.put('/aiyoloapi/mobile/model-update-devices/{installation_id}')
    async def bind(installation_id: str, request: Request):
        principal, service = await identity(request)
        body = await read_body(request, PAGE_BYTES)
        # Canonical origin comes from validated request URL, never untrusted body
        # or arbitrary forwarded headers. TLS terminator must preserve Host/scheme.
        origin = str(request.base_url).rstrip('/')
        result = await run_in_threadpool(service.store.bind, principal.account_id, origin, installation_id, body)
        await run_in_threadpool(service.projection.one, result['binding']['deviceId'])
        return result

    @router.delete('/aiyoloapi/mobile/model-update-devices/{device_id}')
    async def unbind(device_id: str, request: Request):
        principal, service = await identity(request, device_id)
        return await run_in_threadpool(service.store.unbind, principal.account_id, device_id, await read_body(request, PAGE_BYTES))

    @router.put('/aiyoloapi/mobile/model-update-devices/{device_id}/inventory')
    async def inventory(device_id: str, request: Request):
        principal, service = await identity(request, device_id)
        result = await run_in_threadpool(service.store.inventory, principal.account_id, device_id,
                                         await read_body(request, 2 * PAGE_BYTES))
        # Projection is durable/rebuildable; failure must not undo accepted inventory.
        service.wake()
        return result

    @router.get('/aiyoloapi/mobile/model-updates')
    async def delta(request: Request):
        limit = query(request, {'deviceId', 'cursor', 'limit'})
        device_id, cursor = request.query_params.get('deviceId'), request.query_params.get('cursor')
        if not device_id or not cursor:
            raise UpdateError(400, 'invalid_request')
        principal, service = await identity(request, device_id)
        return await run_in_threadpool(service.store.delta, principal.account_id, device_id, cursor, limit)

    @router.get('/aiyoloapi/mobile/model-updates/snapshot')
    async def snapshot(request: Request):
        limit = query(request, {'deviceId', 'pageToken', 'limit'})
        device_id = request.query_params.get('deviceId')
        if not device_id:
            raise UpdateError(400, 'invalid_request')
        principal, service = await identity(request, device_id)
        return await run_in_threadpool(service.store.snapshot, principal.account_id, device_id,
                                      request.query_params.get('pageToken'), limit)

    @router.post('/aiyoloapi/mobile/model-update-reports')
    async def reports(request: Request):
        principal = authenticated(request)
        body = await read_body(request, PAGE_BYTES)
        validate(body, 'report_request')
        principal, service = await identity(request, body['binding']['deviceId'], principal)
        return await run_in_threadpool(service.store.reports, principal.account_id, body)

    @router.get('/aiyoloapi/projects/{project_id}/model-update-status')
    async def status(project_id: str, request: Request):
        limit = query(request, {'updateId', 'deviceStatus', 'pageToken', 'limit'})
        principal, service = await identity(request)
        try:
            context = await run_in_threadpool(resolve_project_context, principal, project_id)
        except Exception as exc:
            if getattr(exc, 'status_code', None) in {403, 404}:
                raise UpdateError(403, 'access_revoked') from None
            raise
        if PROJECT_MODELS_ASSIGN not in context.capabilities:
            raise UpdateError(403, 'access_revoked')
        request.state.project_id = project_id
        if context.platform_entry:
            await run_in_threadpool(_audit_platform_entry, context, request, 'HTTP')
        args = dict(projectId=project_id, updateId=request.query_params.get('updateId'),
                    deviceStatus=request.query_params.get('deviceStatus'), pageToken=request.query_params.get('pageToken'), limit=limit)
        validate(dict(messageType='status_request', contractVersion=1, **args), 'status_request')
        return await run_in_threadpool(service.status, principal.account_id, args)

    return router
