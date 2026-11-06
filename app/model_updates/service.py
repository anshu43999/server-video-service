"""Startup/60-second anti-entropy plus wakeable best-effort immediate scans."""
import asyncio
from datetime import timedelta
import logging
import os
import secrets
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import LargeBinary, String, and_, cast, func, or_, select

from ..database import ProjectRecord, ProjectMembershipRecord

from .models import Device, Inbox, Change, Receipt, PushOutbox, DomainEvent, Ticket, Snapshot, Target, Metric
from .protocol import UpdateError, now, timestamp, utc, response, digest
from .projection import Projection
from .push import FcmSender, PushDispatcher
from .store import UpdateStore

log = logging.getLogger(__name__)


class ModelUpdateService:
    def __init__(self, database, catalog, scenes, sender=None):
        self.store = UpdateStore(database)
        self.projection = Projection(self.store, catalog, scenes)
        self.store.authority = self.projection.authorized
        self.sender = sender or FcmSender(os.environ.get('MODEL_UPDATE_FCM_PROJECT_ID'),
                                          os.environ.get('MODEL_UPDATE_FCM_CREDENTIALS_PATH'))
        self.dispatcher = PushDispatcher(self.store, self.sender, should_stop=lambda: self._closing)
        self._wake = None
        self._task = None
        self._delivery_task = None
        self._loop = None
        self.last_scan = None
        self.last_error = None
        self.push_results = {}
        self._closing = False

    def wake(self):
        if self._wake is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._wake.set)

    async def start(self):
        if not self.store.database.enabled:
            self.last_error = 'database_not_configured'
            return
        self._loop, self._wake = asyncio.get_running_loop(), asyncio.Event()
        self._closing = False
        from .events import configure_notifier
        configure_notifier(self.wake)
        await self.scan()
        self._task = asyncio.create_task(self._run(), name='model-update-compensation')
        self._delivery_task = asyncio.create_task(self._deliver(), name='model-update-delivery')

    async def close(self):
        from .events import configure_notifier
        configure_notifier(None)
        self._closing = True
        if self._task:
            # Cancelling to_thread does not stop its DB worker. Drain it before
            # lifespan disposes the database engine.
            self._wake.set()
            await self._task
        if self._delivery_task:
            await self._delivery_task
        self._delivery_task = None
        self._task, self._wake, self._loop = None, None, None

    async def scan(self):
        try:
            self.last_scan = await asyncio.to_thread(self.projection.scan)
            await asyncio.to_thread(self.store.observe, 'projection_scan_seconds', self.last_scan['elapsedSeconds'])
            self.last_error = 'projection_incomplete' if self.last_scan['failedDevices'] else None
        except Exception:
            self.last_error = 'projection_unavailable'
            log.warning('model update anti-entropy unavailable')

    async def _run(self):
        next_scan, next_cleanup = self._loop.time() + 60, self._loop.time()
        while not self._closing:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
            if self._closing:
                break
            immediate = self._wake.is_set()
            self._wake.clear()
            if immediate or self._loop.time() >= next_scan:
                await self.scan()
                next_scan = self._loop.time() + 60
            if self._closing:
                break
            if self._loop.time() >= next_cleanup:
                try:
                    await asyncio.to_thread(self.store.cleanup)
                    next_cleanup = self._loop.time() + 3600
                except Exception:
                    self.last_error = 'cleanup_unavailable'
                    log.warning('model update cleanup unavailable')

    async def _deliver(self):
        # Slow/unreachable FCM must never postpone the 60-second reconciliation.
        while not self._closing:
            try:
                self.push_results = await asyncio.to_thread(self.dispatcher.dispatch)
            except Exception:
                self.last_error = 'delivery_unavailable'
                log.warning('model update delivery unavailable')
            if not self._closing:
                await asyncio.sleep(1)

    def status(self, account_id, args):
        with self.store.database.session() as session:
            account = self.store.account(session, account_id)
            project = session.get(ProjectRecord, args['projectId'], populate_existing=True)
            member = session.get(ProjectMembershipRecord, (args['projectId'], account_id), populate_existing=True)
            if (project is None or project.lifecycle_state != 'ACTIVE' or
                    account.platform_role != 'PLATFORM_ADMIN' and
                    (member is None or not member.enabled or member.project_role != 'PROJECT_OWNER')):
                raise UpdateError(403, 'access_revoked')
            # Server-side page tickets, bound to requester and exact filter set.
            scope = digest({k: v for k, v in args.items() if k not in {'pageToken', 'limit'}})
            offset = ''
            if args['pageToken']:
                ticket = session.get(Ticket, sha256(args['pageToken'].encode()).hexdigest())
                if (ticket is None or ticket.kind != 'status' or utc(ticket.expires_at) <= now() or
                        ticket.payload.get('accountId') != account_id):
                    raise UpdateError(410, 'snapshot_expired')
                if ticket.payload['scope'] != scope:
                    raise UpdateError(410, 'snapshot_expired')
                offset = ticket.payload['after']
            query = select(Inbox, Device).join(Device, Device.device_id == Inbox.device_id).where(
                Inbox.project_id == args['projectId'], Device.revoked.is_(False))
            if args['updateId']:
                query = query.where(Inbox.update_id == args['updateId'])
            else:
                query = query.where(Inbox.is_current.is_(True))
            items, keys = [], []
            # Keyset windows bound memory even if most rows became invisible.
            after = offset.split('/', 1) if offset else None
            while len(items) <= args['limit']:
                window = query
                if after:
                    window = window.where(or_(Inbox.device_id > after[0],
                        and_(Inbox.device_id == after[0], Inbox.update_id > after[1])))
                rows = session.execute(window.order_by(Inbox.device_id, Inbox.update_id).limit(200)).all()
                if not rows:
                    break
                for row, device in rows:
                    after = (row.device_id, row.update_id)
                    if args['deviceStatus'] and row.payload['stage'] != args['deviceStatus']:
                        continue
                    if not self.store.visible(session, device, row.payload):
                        continue
                    keys.append(row.device_id + '/' + row.update_id)
                    items.append(dict(deviceId=device.device_id, updateId=row.update_id, stage=row.payload['stage'],
                        discovery=row.payload['discovery'], lastContact=timestamp(device.last_contact),
                        staleContact=utc(device.last_contact) < now() - timedelta(days=7), errorCode=row.payload['errorCode']))
                    if len(items) > args['limit']:
                        break
            more = len(items) > args['limit']
            items = items[:args['limit']]
            token = None
            if more:
                token = secrets.token_urlsafe(32)
                session.add(Ticket(token_digest=sha256(token.encode()).hexdigest(), device_id=None, kind='status',
                    payload={'scope': scope, 'after': keys[len(items)-1], 'accountId': account_id},
                    expires_at=now()+timedelta(minutes=10)))
            return response('status_response', items=items, nextPageToken=token, serverTime=timestamp())

    def metrics(self):
        if not self.store.database.enabled:
            return dict(status='database_not_configured', pushEnabled=self.sender.enabled)
        with self.store.database.session() as session:
            result = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
                      for model in (Device, Inbox, Change, Receipt, PushOutbox, DomainEvent)}
            result['pendingPushBindings'] = session.scalar(select(func.count()).select_from(PushOutbox).where(
                PushOutbox.dirty_sequence > PushOutbox.sent_sequence))
            result['pendingDomainEvents'] = session.scalar(select(func.count()).select_from(DomainEvent).where(
                DomainEvent.processed_at.is_(None)))
            oldest = session.scalar(select(func.min(DomainEvent.created_at)).where(DomainEvent.processed_at.is_(None)))
            oldest_age = max(0, (now() - utc(oldest)).total_seconds()) if oldest else 0
            oldest_push = session.scalar(select(func.min(PushOutbox.dirty_since)).where(
                PushOutbox.dirty_sequence > PushOutbox.sent_sequence))
            retries = session.scalar(select(func.coalesce(func.sum(PushOutbox.attempts), 0)))
            measurements = {row.metric_key: dict(count=row.count, total=row.total, maximum=row.maximum)
                            for row in session.scalars(select(Metric))}
            sizes = {}
            for model, column in ((Device, Device.inventory), (Device, Device.source_epochs), (Target, Target.payload),
                    (Device, Device.lifecycle_inventory), (Device, Device.lifecycle_facts),
                    (Inbox, Inbox.payload), (Change, Change.payload), (Receipt, Receipt.payload),
                    (Snapshot, Snapshot.payload), (Snapshot, Snapshot.lifecycle_payload),
                    (Ticket, Ticket.payload), (DomainEvent, DomainEvent.payload)):
                length = func.pg_column_size(column) if self.store.database.backend == 'postgresql' else func.length(
                    cast(cast(column, String), LargeBinary))
                sizes[model.__tablename__ + '.' + column.key] = session.scalar(select(func.coalesce(func.sum(length), 0)))
        return dict(counts=result, lastScan=self.last_scan, lastError=self.last_error,
                    oldestPendingEventSeconds=oldest_age, pendingPushAttempts=retries,
                    oldestPendingPushSeconds=max(0, (now() - utc(oldest_push)).total_seconds()) if oldest_push else 0,
                    documentStorageBytes=sizes, measurements=measurements,
                    pushEnabled=self.sender.enabled, providerResults=self.push_results)
