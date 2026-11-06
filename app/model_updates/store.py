"""PostgreSQL-backed control plane. Never falls back to process memory.

Lock order: rate buckets (separate transaction), installation, binding, child rows.
All writers of a binding's inbox take that binding lock before assigning sequence.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import secrets
from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from ..database import AccountRecord, ProjectRecord, ProjectMembershipRecord
from .models import Installation, Device, Target, Inbox, Change, Receipt, Ticket, Snapshot, PushOutbox, RateBucket, DomainEvent, Metric
from .protocol import (UpdateError, byte_size, digest, now, timestamp, utc, validate, response,
                       target_digest, source_identity, valid_transition, ITEM_BYTES, PAGE_BYTES, TERMINAL, MAX_INTEGER)
from .lifecycle import LifecycleStoreMixin, enabled as lifecycle_enabled


def _insert_once(session, model, key, **fields):
    row = session.get(model, key)
    if row is None:
        try:
            with session.begin_nested():
                row = model(**fields)
                session.add(row)
                session.flush()
        except IntegrityError:
            row = session.get(model, key)
    return row


class UpdateStore(LifecycleStoreMixin):
    def __init__(self, database):
        self.database = database

    def require_storage(self):
        if not self.database.enabled:
            raise UpdateError(503, 'temporarily_unavailable')

    @staticmethod
    def measure(session, key, value=0):
        _insert_once(session, Metric, key, metric_key=key, count=0, total=0, maximum=0)
        row = session.scalar(select(Metric).where(Metric.metric_key == key).with_for_update()
                             .execution_options(populate_existing=True))
        row.count = min(MAX_INTEGER, row.count + 1)
        row.total += value
        row.maximum = max(row.maximum, value)

    def observe(self, key, value=0):
        if self.database.enabled:
            with self.database.session() as session:
                self.measure(session, key, value)

    def rate_limit(self, key, *, global_rate=200, global_burst=400, rate=2, burst=10, shared_global=True):
        """Shared token buckets. Rejected requests still commit replenishment."""
        self.require_storage()
        retry = False
        with self.database.session() as session:
            # Sorted keys ensure concurrent workers always acquire in one order.
            buckets = [('0:global', global_rate, global_burst)] if shared_global else []
            buckets.append(('1:' + key, rate, burst))
            for name, speed, capacity in buckets:
                micros = int(now().timestamp() * 1000000)
                _insert_once(session, RateBucket, name, bucket_key=name, tokens=capacity * 1000000, updated_micros=micros)
                row = session.scalar(select(RateBucket).where(RateBucket.bucket_key == name).with_for_update().execution_options(populate_existing=True))
                if self.database.backend == 'postgresql':
                    micros = session.scalar(text('SELECT floor(extract(epoch FROM clock_timestamp()) * 1000000)::bigint'))
                row.tokens = min(capacity * 1000000, row.tokens + max(0, micros - row.updated_micros) * speed)
                row.updated_micros = max(row.updated_micros, micros)
                if row.tokens < 1000000:
                    retry = True
                else:
                    row.tokens -= 1000000
            if retry:
                self.measure(session, 'rate_limited_fcm' if key == 'fcm:egress' else 'rate_limited_control')
        if retry:
            raise UpdateError(429, 'rate_limited', 1)

    @staticmethod
    def binding(device):
        return dict(origin=device.origin, accountId=device.account_id, deviceId=device.device_id, bindingEpoch=device.epoch)

    @staticmethod
    def account(session, account_id):
        account = session.get(AccountRecord, account_id, populate_existing=True)
        if account is None or not account.enabled:
            raise UpdateError(401, 'login_required')
        return account

    def allowed(self, session, device, project_id):
        account = self.account(session, device.account_id)
        project = session.get(ProjectRecord, project_id, populate_existing=True)
        member = session.get(ProjectMembershipRecord, (project_id, device.account_id), populate_existing=True)
        return bool(project and project.lifecycle_state == 'ACTIVE' and
                    (account.platform_role == 'PLATFORM_ADMIN' or member and member.enabled))

    def visible(self, session, device, item):
        return (self.allowed(session, device, item['release']['projectId']) and
                (not hasattr(self, 'authority') or self.authority(session, device, item)))

    def locked_device(self, session, account_id, device_id, assertion=None, *, revoked=False):
        self.account(session, account_id)
        device = session.scalar(select(Device).where(Device.device_id == device_id).with_for_update().execution_options(populate_existing=True))
        if device is None or device.account_id != account_id:
            raise UpdateError(403, 'access_revoked')
        if assertion is not None and assertion != self.binding(device):
            raise UpdateError(409, 'binding_changed')
        if device.revoked and not revoked:
            raise UpdateError(409, 'binding_changed')
        device.last_contact = now()
        return device

    def bind(self, account_id, origin, installation_id, body):
        self.require_storage()
        validate(body, 'binding_request')
        if body['installationId'] != installation_id:
            raise UpdateError(400, 'invalid_request')
        validate(dict(origin=origin, accountId=account_id, deviceId='new', bindingEpoch=1), 'binding')
        with self.database.session() as session:
            self.account(session, account_id)
            _insert_once(session, Installation, installation_id, installation_id=installation_id, epoch=0)
            install = session.scalar(select(Installation).where(Installation.installation_id == installation_id).with_for_update().execution_options(populate_existing=True))
            device = session.scalar(select(Device).where(Device.device_id == install.device_id).with_for_update()) if install.device_id else None
            if device is None or device.revoked or device.account_id != account_id or device.origin != origin:
                if device is not None:
                    device.revoked, device.push_token = True, None
                    session.execute(delete(PushOutbox).where(PushOutbox.device_id == device.device_id))
                if install.epoch >= MAX_INTEGER:
                    raise UpdateError(409, 'binding_changed')
                install.epoch += 1
                device = Device(device_id=str(uuid4()), installation_id=installation_id, account_id=account_id,
                    origin=origin, epoch=install.epoch, capabilities=body['capabilities'], push_provider='none',
                    token_generation=0, notification_permission=body['notificationPermission'])
                session.add(device)
                session.flush()
                install.device_id = device.device_id
            if body['tokenGeneration'] == device.token_generation and body['token'] != device.push_token:
                raise UpdateError(409, 'binding_changed')
            if body['tokenGeneration'] >= device.token_generation:
                device.push_token, device.token_generation = body['token'], body['tokenGeneration']
                device.push_provider = body['pushProvider']
            device.capabilities, device.notification_permission = deepcopy(body['capabilities']), body['notificationPermission']
            device.last_contact = now()
            fields = dict(binding=self.binding(device), serverTime=timestamp())
            if 1 in body['capabilities'].get('resourceLifecycleVersions', []):
                fields['resourceLifecycleVersion'] = 1
            return response('binding_response', **fields)

    def unbind(self, account_id, device_id, body):
        self.require_storage()
        validate(body, 'unbind_request')
        with self.database.session() as session:
            device = self.locked_device(session, account_id, device_id, body['binding'], revoked=True)
            device.revoked, device.push_token = True, None
            session.execute(delete(PushOutbox).where(PushOutbox.device_id == device_id))
            return response('unbind_response', revoked=True)

    def inventory(self, account_id, device_id, body):
        self.require_storage()
        if byte_size(body) > 2 * PAGE_BYTES:
            raise UpdateError(413, 'capacity_exceeded')
        if isinstance(body, dict):
            count = sum(len(body.get(key, [])) for key in ('entries', 'lifecycleEntries')
                        if isinstance(body.get(key, []), list))
            if count > 1000:
                raise UpdateError(413, 'capacity_exceeded')
        validate(body, 'inventory_request')
        entries = body['entries']
        if len({item['entryId'] for item in entries}) != len(entries):
            raise UpdateError(400, 'invalid_request')
        if len({source_identity(item['source']) for item in entries}) != len(entries):
            raise UpdateError(400, 'invalid_request')
        for item in entries:
            source = item['source']
            if source['kind'] == 'scene':
                selection = source['selection']
                if (selection != {k: sorted(set(v)) for k, v in selection.items()} or
                        digest(selection) != source['selectionDigest']):
                    raise UpdateError(400, 'invalid_request')
        identity = digest([entries, body['lifecycleEntries']]) if 'lifecycleEntries' in body else digest(entries)
        with self.database.session() as session:
            device = self.locked_device(session, account_id, device_id, body['binding'])
            revision = body['inventoryRevision']
            if lifecycle_enabled(device) != ('lifecycleEntries' in body):
                raise UpdateError(409, 'target_changed')
            if lifecycle_enabled(device) and revision < device.inventory_revision:
                raise UpdateError(409, 'target_changed')
            if revision == device.inventory_revision and identity != device.inventory_digest:
                raise UpdateError(409, 'target_changed')
            if revision > device.inventory_revision:
                # Inventory revisions cannot resurrect a removed source epoch.
                # Absence in an accepted full inventory retires that epoch; an
                # explicit re-add must use a strictly newer local sourceEpoch.
                epochs = deepcopy(device.source_epochs)
                present = set()
                for entry in entries:
                    key, epoch = source_identity(entry['source']), entry['source']['sourceEpoch']
                    present.add(key)
                    old = epochs.get(key)
                    if old and (epoch < old['epoch'] or epoch == old['epoch'] and
                                (old['retired'] or entry['selectionGeneration'] < old['selectionGeneration'])):
                        raise UpdateError(409, 'target_changed')
                    epochs[key] = dict(epoch=epoch, retired=False, selectionGeneration=entry['selectionGeneration'])
                lifecycle = self.lifecycle_inventory_update(device, body, epochs, present)
                for key, state in epochs.items():
                    if key not in present:
                        state['retired'] = True
                # Retired identities cannot be evicted without permitting replay.
                # Bound the binding's ledger and fail atomically at capacity.
                if len(epochs) > 10000 or byte_size(epochs) > 2 * PAGE_BYTES:
                    raise UpdateError(413, 'capacity_exceeded')
                device.source_epochs = epochs
                device.lifecycle_inventory = lifecycle
                device.inventory, device.inventory_digest, device.inventory_revision = deepcopy(entries), identity, revision
            return response('inventory_response', acceptedRevision=device.inventory_revision, rebuildRequested=False)

    def ticket(self, session, device, kind, payload, expires=None):
        payload = dict(payload, lifecycle=lifecycle_enabled(device), inventoryRevision=device.inventory_revision)
        token = secrets.token_urlsafe(32)
        session.add(Ticket(token_digest=sha256(token.encode()).hexdigest(), device_id=device.device_id,
                           kind=kind, payload=deepcopy(payload), expires_at=expires or now() + timedelta(days=90)))
        return token

    def read_ticket(self, session, device, token, kind):
        if not isinstance(token, str) or not 1 <= len(token) <= 2048:
            raise UpdateError(400, 'invalid_request')
        row = session.get(Ticket, sha256(token.encode()).hexdigest())
        error = 'cursor_expired' if kind == 'cursor' else 'snapshot_expired'
        if row is None or row.device_id != device.device_id or row.kind != kind or utc(row.expires_at) <= now():
            raise UpdateError(410, error)
        if (row.payload.get('lifecycle', False) != lifecycle_enabled(device) or
                lifecycle_enabled(device) and row.payload.get('inventoryRevision') != device.inventory_revision):
            raise UpdateError(410, error)
        return row.payload

    def _change(self, session, device, row, operation='upsert', *, notify=True):
        if device.sequence >= MAX_INTEGER:
            raise UpdateError(413, 'capacity_exceeded')
        if byte_size(row.payload) > ITEM_BYTES:
            raise UpdateError(413, 'capacity_exceeded')
        if row.payload['itemRevision'] > MAX_INTEGER:
            raise UpdateError(413, 'capacity_exceeded')
        validate(row.payload, 'item')
        device.sequence += 1
        row.updated_at = now()
        session.add(Change(device_id=device.device_id, sequence=device.sequence, update_id=row.update_id,
            payload={'sequence': device.sequence, 'operation': operation, 'item': deepcopy(row.payload)}))
        if not notify:
            session.flush()
            return
        push = session.get(PushOutbox, device.device_id)
        if push is None:
            push = PushOutbox(device_id=device.device_id)
            session.add(push)
        if push.dirty_since is None or push.sent_sequence >= push.dirty_sequence:
            push.dirty_since = now()
        push.dirty_sequence = device.sequence
        session.flush()

    def _put(self, session, device, item, source_key):
        validate(item, 'item')
        if byte_size(item) > ITEM_BYTES:
            raise UpdateError(413, 'capacity_exceeded')
        row = session.get(Inbox, (device.device_id, item['updateId']))
        if row is not None:
            # Repeated scans never erase progress/quarantine or mutate target facts.
            old = row.payload
            old_target, new_target = deepcopy(old['target']), deepcopy(item['target'])
            if old_target:
                old_target.pop('supersedesUpdateId', None)
            if new_target:
                new_target.pop('supersedesUpdateId', None)
            if old_target != new_target or old['release'] != item['release']:
                raise UpdateError(409, 'target_changed')
            return False
        if item['target'] is not None:
            target = session.get(Target, item['updateId'])
            if target is None:
                session.add(Target(update_id=item['updateId'], source_key=source_key, payload=deepcopy(item['target'])))
            elif target.payload != item['target']:
                raise UpdateError(409, 'target_changed')
        row = Inbox(device_id=device.device_id, update_id=item['updateId'], project_id=item['release']['projectId'],
                    source_key=source_key, payload=deepcopy(item), report_seq=0)
        session.execute(update(Inbox).where(Inbox.device_id == device.device_id, Inbox.source_key == source_key)
                        .values(is_current=False))
        session.add(row)
        self._change(session, device, row)
        return True

    @staticmethod
    def _page(items, limit, overhead=8192):
        result, size = [], overhead
        for item in items:
            length = byte_size(item) + 1
            if length > ITEM_BYTES + 128:
                raise UpdateError(413, 'capacity_exceeded')
            if len(result) >= limit or size + length > PAGE_BYTES:
                break
            result.append(item)
            size += length
        if items and not result:
            raise UpdateError(413, 'capacity_exceeded')
        return result

    def snapshot(self, account_id, device_id, page_token=None, limit=100):
        self.require_storage()
        if type(limit) is not int or not 1 <= limit <= 200:
            raise UpdateError(400, 'invalid_request')
        with self.database.session() as session:
            device = self.locked_device(session, account_id, device_id)
            if page_token:
                page = self.read_ticket(session, device, page_token, 'snapshot')
                snapshot = session.get(Snapshot, page['snapshotId'])
                if snapshot is None or snapshot.device_id != device_id or utc(snapshot.expires_at) <= now():
                    raise UpdateError(410, 'snapshot_expired')
                offset, page_index = page['offset'], page.get('pageIndex', 0)
            else:
                items, total = [], 0
                rows = session.scalars(select(Inbox).where(Inbox.device_id == device_id, Inbox.is_current.is_(True))
                                       .order_by(Inbox.update_id).execution_options(yield_per=200))
                for row in rows:
                    if not self.visible(session, device, row.payload):
                        continue
                    total += byte_size(row.payload)
                    if len(items) >= 10000 or total > 16 * PAGE_BYTES:
                        raise UpdateError(413, 'capacity_exceeded')
                    items.append(deepcopy(row.payload))
                lifecycle, coverage = self.lifecycle_snapshot(session, device)
                items.extend(lifecycle)
                if len(items) > 11000 or byte_size(items) > 16 * PAGE_BYTES:
                    raise UpdateError(413, 'capacity_exceeded')
                cursor = self.ticket(session, device, 'cursor', {'sequence': device.sequence})
                snapshot = Snapshot(snapshot_id=str(uuid4()), device_id=device_id, sequence=device.sequence, payload=items,
                                    lifecycle_payload=coverage, cursor=cursor, expires_at=now() + timedelta(minutes=10))
                session.add(snapshot)
                offset, page_index = 0, 0
            # Never release a fixed historical page after membership changes.
            for item in snapshot.payload:
                if item['kind'] == 'resource_lifecycle':
                    self.lifecycle_read_guard(session, device, item, 'snapshot_expired')
                elif not self.visible(session, device, item):
                    raise UpdateError(410, 'snapshot_expired') if lifecycle_enabled(device) else UpdateError(403, 'access_revoked')
            if bool(snapshot.lifecycle_payload) != lifecycle_enabled(device):
                raise UpdateError(410, 'snapshot_expired')
            if snapshot.lifecycle_payload and snapshot.lifecycle_payload['inventoryRevision'] != device.inventory_revision:
                raise UpdateError(410, 'snapshot_expired')
            page_items = self._page(snapshot.payload[offset:], limit)
            next_offset = offset + len(page_items)
            token = self.ticket(session, device, 'snapshot', dict(snapshotId=snapshot.snapshot_id,
                offset=next_offset, pageIndex=page_index + 1), snapshot.expires_at) if next_offset < len(snapshot.payload) else None
            fields = dict(binding=self.binding(device), snapshotId=snapshot.snapshot_id,
                snapshotCursor=snapshot.cursor, expiresAt=timestamp(snapshot.expires_at),
                nextPageToken=token, serverTime=timestamp())
            fields['items'] = [item for item in page_items if item['kind'] != 'resource_lifecycle']
            if snapshot.lifecycle_payload:
                from .lifecycle import binding
                fields['lifecycleSnapshot'] = dict(messageType='lifecycle_snapshot_page', binding=binding(device),
                    inventoryRevision=snapshot.lifecycle_payload['inventoryRevision'], snapshotId=snapshot.snapshot_id,
                    snapshotCursor=snapshot.cursor, pageIndex=page_index,
                    inventoryCount=snapshot.lifecycle_payload['inventoryCount'],
                    coveredCount=sum(item['kind'] == 'resource_lifecycle' for item in snapshot.payload[:next_offset]),
                    nextPageToken=token, items=[item for item in page_items if item['kind'] == 'resource_lifecycle'])
            return response('snapshot_response', **fields)

    def delta(self, account_id, device_id, cursor, limit=100):
        self.require_storage()
        if type(limit) is not int or not 1 <= limit <= 200:
            raise UpdateError(400, 'invalid_request')
        with self.database.session() as session:
            device = self.locked_device(session, account_id, device_id)
            seq = self.read_ticket(session, device, cursor, 'cursor')['sequence']
            if seq < device.cursor_floor or seq > device.sequence:
                raise UpdateError(410, 'cursor_expired')
            # Scan bounded windows; advance past invisible facts without leaking them.
            rows = session.scalars(select(Change).where(Change.device_id == device_id, Change.sequence > seq)
                                   .order_by(Change.sequence).limit(201)).all()
            items, end = [], seq
            for row in rows:
                candidate = row.payload
                if candidate.get('operation') == 'lifecycle':
                    if not lifecycle_enabled(device):
                        end = row.sequence
                        continue
                    self.lifecycle_read_guard(session, device, candidate['item'])
                elif not self.visible(session, device, candidate['item']):
                    end = row.sequence
                    continue
                if len(self._page(items + [candidate], limit)) <= len(items):
                    break
                items.append(deepcopy(candidate))
                end = row.sequence
            more = end < device.sequence
            if not items and more:
                # A revoked history window must not produce a non-progressing
                # empty nonterminal page; rebuild the current permission snapshot.
                raise UpdateError(410, 'cursor_expired')
            next_cursor = cursor if end == seq else self.ticket(session, device, 'cursor', {'sequence': end})
            return response('delta_response', binding=self.binding(device), fromCursor=cursor, nextCursor=next_cursor,
                            items=items, hasMore=more, serverTime=timestamp())

    def reports(self, account_id, body):
        self.require_storage()
        if byte_size(body) > PAGE_BYTES:
            raise UpdateError(413, 'capacity_exceeded')
        if isinstance(body, dict) and isinstance(body.get('reports'), list) and len(body['reports']) > 100:
            raise UpdateError(413, 'capacity_exceeded')
        validate(body, 'report_request')
        with self.database.session() as session:
            device = self.locked_device(session, account_id, body['binding']['deviceId'], body['binding'])
            results = []
            for report in body['reports']:
                event_id, identity = report['eventId'], digest(report)
                existing = session.get(Receipt, (device.device_id, event_id))
                result = dict(eventId=event_id, outcome='accepted', permanent=False, errorCode=None)
                if report.get('reportKind') == 'resource_lifecycle':
                    results.append(self.lifecycle_report(session, device, report))
                    continue
                row = session.get(Inbox, (device.device_id, report['updateId']))
                # A replaced download may finish its file, but cannot commit its
                # old approval. Permit only its exact terminal cancellation fact
                # so that one-running + latest-successor eventually converges.
                if (row is not None and row.payload['target'] is not None and
                        report['stage'] == 'superseded' and
                        row.payload['stage'] in {'downloading', 'verifying', 'staged', 'warming', 'committing'} and
                        report['digest'] == row.payload['target']['targetDigest'] and
                        row.authority_revision <= report['itemRevision'] <= row.payload['itemRevision'] and
                        report['reportSeq'] > row.report_seq and
                        existing is None and
                        self.allowed(session, device, row.project_id)):
                    successors = session.scalars(select(Inbox).where(Inbox.device_id == device.device_id,
                        Inbox.source_key == row.source_key, Inbox.is_current.is_(True))).all()
                    if any(candidate.update_id != row.update_id and candidate.payload['target'] and
                           candidate.payload['target']['source'] == row.payload['target']['source'] and
                           self.visible(session, device, candidate.payload) for candidate in successors):
                        item = deepcopy(row.payload)
                        item['stage'], item['errorCode'] = 'superseded', 'target_changed'
                        item['itemRevision'] += 1
                        row.payload = item
                        self._change(session, device, row, notify=False)
                if row is not None and not self.visible(session, device, row.payload):
                    code = 'target_changed' if self.allowed(session, device, row.project_id) else 'access_revoked'
                    result.update(outcome='rejected', permanent=True, errorCode=code)
                    if existing is None:
                        session.add(Receipt(device_id=device.device_id, event_id=event_id, update_id=report['updateId'],
                            payload_digest=identity, payload=deepcopy(report), result=deepcopy(result)))
                        session.flush()
                    results.append(result)
                    continue
                if existing is not None:
                    result = deepcopy(existing.result)
                    if existing.payload_digest != identity:
                        result.update(outcome='rejected', permanent=True, errorCode='event_payload_conflict')
                    elif row is not None and report['itemRevision'] < row.authority_revision:
                        result.update(outcome='stale', permanent=True, errorCode='stale_report')
                    elif result['outcome'] == 'accepted':
                        result['outcome'] = 'duplicate'
                    results.append(result)
                    continue
                if row is None or not self.allowed(session, device, row.project_id):
                    result.update(outcome='rejected', permanent=True, errorCode='access_revoked')
                elif not self.visible(session, device, row.payload):
                    result.update(outcome='rejected', permanent=True, errorCode='target_changed')
                elif report['itemRevision'] < row.authority_revision or report['reportSeq'] <= row.report_seq:
                    result.update(outcome='stale', permanent=True, errorCode='stale_report')
                elif report['itemRevision'] > row.payload['itemRevision']:
                    result.update(outcome='rejected', permanent=True, errorCode='target_changed')
                elif report['digest'] != (row.payload['target']['targetDigest'] if row.payload['target'] else digest(row.payload['release'])):
                    result.update(outcome='rejected', permanent=True, errorCode='target_changed')
                elif report['stage'] == 'installed' and (not row.payload['target'] or report['completedCriteria'] != row.payload['target']['successCriteria']):
                    result.update(outcome='rejected', permanent=True, errorCode='criteria_mismatch')
                elif not row.payload['target'] and report['stage'] not in {'discovered', 'seen'}:
                    result.update(outcome='rejected', permanent=True, errorCode='target_changed')
                elif report['stage'] not in {'discovered', 'seen'} and not valid_transition(row.payload['stage'], report['stage']):
                    result.update(outcome='rejected', permanent=True, errorCode='invalid_transition')
                else:
                    item = deepcopy(row.payload)
                    if report['stage'] in {'discovered', 'seen'}:
                        if item['discovery'] != 'seen':
                            item['discovery'] = report['stage']
                    else:
                        item['stage'], item['errorCode'] = report['stage'], report['errorCode']
                    # Progress advances projection revision for merge consistency.
                    # Queued receipts may reference earlier observations of the
                    # same authority generation, never a retired approval.
                    changed = item != row.payload
                    if changed:
                        item['itemRevision'] += 1
                    row.report_seq, row.payload = report['reportSeq'], item
                    if changed:
                        self._change(session, device, row, notify=False)
                session.add(Receipt(device_id=device.device_id, event_id=event_id, update_id=report['updateId'],
                    payload_digest=identity, payload=deepcopy(report), result=deepcopy(result)))
                session.flush()
                results.append(result)
            return response('report_response', results=results)

    def cleanup(self):
        """Terminal-only retention, expired pages; active pending facts never TTL out."""
        cutoff = now() - timedelta(days=90)
        with self.database.session() as session:
            for device_id in session.scalars(select(Device.device_id).order_by(Device.device_id)):
                device = session.scalar(select(Device).where(Device.device_id == device_id).with_for_update())
                lifecycle_last = session.scalar(select(func.max(Change.sequence)).where(
                    Change.device_id == device_id, Change.update_id.is_(None), Change.created_at < cutoff))
                if lifecycle_last:
                    device.cursor_floor = max(device.cursor_floor, lifecycle_last)
                    session.execute(delete(Change).where(Change.device_id == device_id,
                        Change.update_id.is_(None), Change.created_at < cutoff))
                rows = session.scalars(select(Inbox).where(Inbox.device_id == device_id, Inbox.updated_at < cutoff)).all()
                for row in rows:
                    if row.payload['stage'] not in TERMINAL:
                        continue
                    # Expire cursors crossing removed history; keep current inbox fact for snapshots.
                    last = session.scalar(select(func.max(Change.sequence)).where(Change.device_id == device_id,
                                         Change.update_id == row.update_id, Change.created_at < cutoff))
                    if last:
                        device.cursor_floor = max(device.cursor_floor, last)
                        session.execute(delete(Change).where(Change.device_id == device_id,
                            Change.update_id == row.update_id, Change.created_at < cutoff))
                    session.execute(delete(Receipt).where(Receipt.device_id == device_id,
                        Receipt.update_id == row.update_id, Receipt.created_at < cutoff))
                    if not row.is_current:
                        session.delete(row)
            # Permanent rejections for missing targets are terminal too. Active
            # receipts remain until their pending object reaches a terminal fact.
            active = select(Inbox.update_id).where(Inbox.device_id == Receipt.device_id)
            session.execute(delete(Receipt).where(Receipt.created_at < cutoff, ~Receipt.update_id.in_(active)))
            session.execute(delete(Receipt).where(Receipt.created_at < cutoff, Receipt.update_id.is_(None)))
            session.execute(delete(Target).where(~Target.update_id.in_(select(Inbox.update_id)),
                                                 ~Target.update_id.in_(select(Change.update_id))))
            session.execute(delete(DomainEvent).where(DomainEvent.processed_at < cutoff))
            session.execute(delete(Ticket).where(Ticket.expires_at < now()))
            session.execute(delete(Snapshot).where(Snapshot.expires_at < now()))
