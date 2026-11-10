import asyncio
import threading
import unittest

from app.catalog_reads import CatalogReads, CatalogReadBusy, CatalogReadTimeout


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.001)


class CatalogReadsTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_workers_admit_no_waiting_queue_and_keep_event_loop_live(self):
        reader = CatalogReads()
        self.addCleanup(reader.close)
        release = threading.Event()
        self.addCleanup(release.set)
        started = [threading.Event(), threading.Event()]
        def read(index):
            started[index].set()
            release.wait(3)
            return index
        tasks = [asyncio.create_task(reader.run(lambda index=i: read(index))) for i in range(2)]
        await until(lambda: all(event.is_set() for event in started))
        for _ in range(20):
            with self.assertRaises(CatalogReadBusy):
                await reader.run(lambda: self.fail('overflow must not execute'))
        release.set()
        self.assertEqual([0, 1], await asyncio.gather(*tasks))

    async def test_cancelled_waiter_does_not_release_running_slot(self):
        reader = CatalogReads(workers=1)
        self.addCleanup(reader.close)
        release, started = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def read():
            started.set(); release.wait(3)
            return 'late'
        task = asyncio.create_task(reader.run(read))
        await until(started.is_set)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(CatalogReadBusy):
            await reader.run(lambda: 'must not run')
        release.set()
        async def retry():
            while True:
                try:
                    return await reader.run(lambda: 'fresh')
                except CatalogReadBusy:
                    await asyncio.sleep(.001)
        self.assertEqual('fresh', await asyncio.wait_for(retry(), 2))

    async def test_timeout_retains_slot_until_actual_completion(self):
        reader = CatalogReads(workers=1, timeout=.03)
        self.addCleanup(reader.close)
        release = threading.Event()
        self.addCleanup(release.set)
        with self.assertRaises(CatalogReadTimeout):
            await reader.run(lambda: release.wait(3))
        with self.assertRaises(CatalogReadBusy):
            await reader.run(lambda: 'must not run')
        release.set()

    async def test_failure_releases_slot_and_preserves_error(self):
        reader = CatalogReads(workers=1)
        self.addCleanup(reader.close)
        def fail():
            raise ValueError('fixture error')
        with self.assertRaisesRegex(ValueError, 'fixture error'):
            await reader.run(fail)
        self.assertEqual(42, await reader.run(lambda: 42))

    async def test_close_rejects_new_work_without_cancelling_active_read(self):
        reader = CatalogReads(workers=1)
        release, started = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def read():
            started.set(); release.wait(3)
            return 'done'
        task = asyncio.create_task(reader.run(read))
        await until(started.is_set)
        reader.close()
        with self.assertRaises(CatalogReadBusy):
            await reader.run(lambda: None)
        release.set()
        self.assertEqual('done', await task)

    async def test_invalid_limits_are_rejected(self):
        for kwargs in ({'workers': 0}, {'timeout': 0}):
            with self.assertRaises(ValueError):
                CatalogReads(**kwargs)
