"""Bounded, project-scoped exports; complete files are prepared before HTTP 200."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import shutil
import tempfile
from contextlib import nullcontext

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from . import auth
from .database import AlertEventRecord, FalsePositiveFeedbackRecord
from .project_auth import PROJECT_EXPORTS_CREATE, resolve_project_context, authorization_error

MAX_ROWS = 100_000
MAX_BYTES = 128 * 1024 * 1024
_slots = asyncio.Semaphore(2)
ALERT_FIELDS = ('eventId','ruleId','ruleVersion','sourceId','subjectKey','label','displayName',
                'state','severity','notifySeverity','startedAtUs','confirmedAtUs','lastSeenAtUs',
                'modelId','modelVersion','model','provenance','disposition')
FEEDBACK_FIELDS = ('entryId','eventId','projectId','kind','label','modelId','modelVersion','annotations',
                   'detections','detectionResults','effectiveThresholds','thresholds','sourceId',
                   'subjectKey','capturedAtUs','ruleId','ruleVersion','createdAt','expectedLabels','tags',
                   'evidenceUnavailableReason','model','provenance')


def assert_export_access(request, project_id):
    principal = auth.authenticate(request)
    if principal is None or principal.legacy:
        raise auth.authentication_error()
    context = resolve_project_context(principal, project_id)
    if PROJECT_EXPORTS_CREATE not in context.capabilities:
        raise authorization_error(PROJECT_EXPORTS_CREATE)


def report_value(value):
    """Allow useful scalar data, stripping arbitrary URL/inline evidence strings."""
    if isinstance(value, dict):
        return {k: report_value(v) for k, v in value.items()
                if not any(word in k.lower() for word in ('token', 'secret', 'password', 'credential', 'cookie', 'authorization', 'url', 'path', 'image', 'evidence', 'note'))}
    if isinstance(value, list):
        return [report_value(v) for v in value]
    if isinstance(value, str) and any(x in value.lower() for x in ('://', 'data:', 'bearer ', 'password=')):
        return '[redacted]'
    return value


def export_rows(store, project_id, feedback=False):
    db = store.database_manager
    if db is not None:
        model = FalsePositiveFeedbackRecord if feedback else AlertEventRecord
        key = model.entry_id if feedback else model.event_id
        # A single server cursor observes one statement snapshot, without ORM
        # materialization of all rows. The file is spooled, not kept in RAM.
        with db.session() as session:
            fields = (*FEEDBACK_FIELDS, 'image', 'screenshot') if feedback else ALERT_FIELDS
            result = session.execute(select(*(model.payload[k].label(k) for k in fields)).where(model.project_id == project_id)
                                     .order_by(key).execution_options(yield_per=500))
            for row in result:
                yield {k: v for k, v in row._mapping.items() if v is not None}
    else:
        # Development fallback already stores all rows in memory. Snapshot its
        # values under the lock; do not hold the lock across an HTTP transfer.
        with store._lock:
            source = store._feedback if feedback else store._events
            values = [v.copy() for (pid, _), v in source.items() if pid == project_id]
        yield from values


def prepare_export(store, project_id, feedback, check):
    rows = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b')
    output = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b')
    count = 0
    try:
        check()
        for value in export_rows(store, project_id, feedback):
            if count % 500 == 0:
                check()
            fields = FEEDBACK_FIELDS if feedback else ALERT_FIELDS
            if feedback:
                from .alerts.disposition import public_training_entry
                value = public_training_entry(value, project_id)
            item = report_value({k: value[k] for k in fields if k in value})
            if feedback:
                from .alerts.disposition import _safe_ref
                for key in ('image', 'screenshot'):
                    raw = value.get(key)
                    ref = _safe_ref(raw) if raw else None
                    # Portable references only; actual image access still uses
                    # the authenticated project evidence endpoint.
                    item[key] = ref if ref and not any(c in ref for c in (':', '?', '#')) and '..' not in ref.split('/') else None
                if not item.get('image'):
                    item['evidenceUnavailableReason'] = 'reference_not_exportable' if value.get('image') else value.get('evidenceUnavailableReason', 'evidence_not_uploaded')
            item['projectId'] = project_id
            encoded = json.dumps(item, ensure_ascii=False, separators=(',', ':')).encode()
            if count >= MAX_ROWS or rows.tell() + len(encoded) > MAX_BYTES // (2 if feedback else 1) - 4096:
                raise HTTPException(413, detail={'code':'export_limit_exceeded', 'message':'export exceeds 100000 rows or 128 MiB; use an offline scoped archive'})
            if count:
                rows.write(b',')
            rows.write(encoded)
            count += 1
        check()
        metadata = {'format':'aiyolo-false-positive-v1' if feedback else 'aiyolo-alert-report-v1',
                    'projectId':project_id, 'generatedAt':datetime.now(timezone.utc).isoformat(),
                    'count':count, 'scope':'entire-project', 'evidenceIncluded':False}
        output.write(json.dumps(metadata, separators=(',', ':')).encode()[:-1])
        for name in (('entries', 'trainingEntries') if feedback else ('events',)):
            output.write(b',"' + name.encode() + b'":[')
            rows.seek(0)
            shutil.copyfileobj(rows, output, 256 * 1024)
            output.write(b']')
        output.write(b'}\n')
        output.seek(0)
        return output, count
    except BaseException:
        output.close()
        raise
    finally:
        rows.close()


async def export_response(request, context, store, feedback=False):
    # Fail fast; queued exports must not exhaust sockets or temp storage.
    if _slots.locked():
        raise HTTPException(429, detail={'code':'export_busy', 'message':'retry export later'}, headers={'Retry-After':'5'})
    await _slots.acquire()
    output = None
    check = lambda: assert_export_access(request, context.project_id)
    try:
        # Shield + await ensures cancellation cannot orphan a temporary file.
        task = asyncio.create_task(asyncio.to_thread(prepare_export, store, context.project_id, feedback, check))
        try:
            output, count = await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                pending, _ = await task
                pending.close()
            finally:
                raise
        from .project_management import _add_project_audit
        with auth.database.session() if auth.database.enabled else nullcontext(None) as session:
            _add_project_audit(session, context, request.headers.get('x-request-id'),
                               'export.false_positives' if feedback else 'export.alerts',
                               'report', context.project_id, None, None, {'rowCount':count})
    except BaseException:
        if output is not None:
            output.close()
        _slots.release()
        raise

    async def chunks():
        while True:
            await asyncio.to_thread(check)
            chunk = output.read(256 * 1024)
            if not chunk:
                break
            yield chunk

    class ReportResponse(StreamingResponse):
        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                output.close()
                _slots.release()

    filename = 'aiyolo-false-positives.json' if feedback else 'aiyolo-alerts.json'
    length = output.seek(0, 2)
    output.seek(0)
    return ReportResponse(chunks(), media_type='application/json', headers={
        'Content-Disposition':f'attachment; filename={filename}', 'Cache-Control':'no-store',
        'Content-Length':str(length),
        'X-Project-Id':context.project_id, 'X-Export-Row-Count':str(count),
    })
