"""Allowlisted catalog timing; never accepts paths, payloads or exception text."""
from __future__ import annotations

import json
import time
from uuid import UUID

from .observability import logger

ROUTES = frozenset({
    '/aiyoloapi/models',
    '/aiyoloapi/projects/{project_id}/models',
    '/aiyoloapi/projects/{project_id}/models/available',
})
OUTCOMES = frozenset({'ok', 'busy', 'timeout', 'cancelled', 'changed', 'denied', 'error'})


class CatalogTelemetry:
    def __init__(self, request_id, route):
        # Use only the server middleware's UUID, never a caller's raw header.
        try:
            self.request_id = str(UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            self.request_id = None
        self.route = route if route in ROUTES else 'unmatched'
        self.started = time.monotonic()

    def _emit(self, event, outcome, duration, **numbers):
        try:
            logger.info(json.dumps({
                'event': event, 'requestId': self.request_id, 'route': self.route,
                'outcome': outcome if outcome in OUTCOMES else 'error',
                'durationMs': round(max(0.0, duration) * 1000, 3),
                **numbers,
            }, separators=(',', ':')))
        except Exception:
            # A failing log sink must not alter permissions, responses or slots.
            # Do not attempt a fallback log that could expose the sink error.
            pass

    def read_finished(self, outcome):
        # The catalog waiter ended; request.finished is HTTP response completion.
        self._emit('catalog.read.finished', outcome, time.monotonic() - self.started)

    def worker_finished(self, outcome, duration, hashes):
        # Called by the worker only, after its checks/cleanup. Never read partial
        # counters from the HTTP thread and never emit per-file events.
        self._emit('catalog.worker.finished', outcome, duration,
                   hashAttempts=hashes.hash_attempts if hashes is not None else 0,
                   hashCompleted=hashes.hash_completed if hashes is not None else 0,
                   hashReuses=hashes.hash_reuses if hashes is not None else 0,
                   hashDurationMs=round(hashes.hash_seconds * 1000, 3) if hashes is not None else 0.0)
