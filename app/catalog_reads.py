"""Process-local admission for expensive, read-only catalog inspections."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from typing import Callable, TypeVar

T = TypeVar('T')


class CatalogReadBusy(Exception):
    pass


class CatalogReadTimeout(Exception):
    pass


class CatalogReads:
    """At most two submitted/running reads; excess requests fail without queuing.

    Cancellation/timeout releases the HTTP waiter, NOT the worker's slot. File
    I/O cannot safely be killed in Python, so that slot remains occupied until
    actual completion. No result cache or cross-account request coalescing.
    """
    def __init__(self, workers: int = 2, timeout: float = 12.0):
        if workers < 1 or timeout <= 0:
            raise ValueError('positive catalog read limits required')
        self.timeout = timeout
        self._slots = BoundedSemaphore(workers)
        self._lock = Lock()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='catalog-read')

    async def run(self, operation: Callable[[], T]) -> T:
        with self._lock:
            if self._closed or not self._slots.acquire(blocking=False):
                raise CatalogReadBusy()
            try:
                future = self._executor.submit(operation)
            except BaseException:
                self._slots.release()
                raise
        future.add_done_callback(lambda _: self._slots.release())
        waiter = asyncio.wrap_future(future)
        # Consume late failures after the HTTP task has gone; never log secrets
        # or permit cancellation to create queued executor tombstones.
        waiter.add_done_callback(lambda result: None if result.cancelled() else result.exception())
        try:
            return await asyncio.wait_for(asyncio.shield(waiter), self.timeout)
        except TimeoutError as exc:
            raise CatalogReadTimeout() from exc

    def close(self):
        with self._lock:
            self._closed = True
            self._executor.shutdown(wait=False, cancel_futures=False)
