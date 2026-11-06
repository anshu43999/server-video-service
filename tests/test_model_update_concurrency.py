"""Independent processes, connections and identity maps; isolated PostgreSQL only."""
import multiprocessing
import os
import unittest
from sqlalchemy import select
from app.database import DatabaseManager
from app.model_updates.models import Change, Device, Installation
from app.model_updates.protocol import UpdateError
from app.model_updates.store import UpdateStore
import test_model_updates as common


def writer(url, device_id, loaded, result):
    db = DatabaseManager(url)
    try:
        store = UpdateStore(db)
        with db.session() as session:
            stale = session.get(Device, device_id)
            result.put(('preloaded', stale.sequence))
            loaded.set()
            device = store.locked_device(session, 'account-one', device_id)
            store._put(session, device, common.item(2), 'source')
        result.put(('committed', device.sequence))
    except Exception as exc:
        result.put(('error', type(exc).__name__))
    finally:
        db.close()


def requests(url, gate, result, operation):
    db = DatabaseManager(url)
    try:
        store = UpdateStore(db)
        if not gate.wait(10):
            raise RuntimeError('gate timeout')
        if operation == 'bind':
            binding = store.bind('account-one', 'https://test.example', 'new-racing-install',
                                 common.binding_request('new-racing-install'))['binding']
            result.put(('bound', binding))
        else:
            outcomes = []
            for _ in range(10):
                try:
                    store.rate_limit('shared-process', rate=0, global_rate=0)
                    outcomes.append(200)
                except UpdateError as exc:
                    outcomes.append(exc.status)
            result.put(('limited', outcomes))
    except Exception as exc:
        result.put(('error', type(exc).__name__))
    finally:
        db.close()


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS') == '1', 'requires isolated PostgreSQL')
class UpdateConcurrencyTests(unittest.TestCase):
    use_postgresql = True

    def setUp(self):
        common.UpdateStoreTests.setUp(self)
        self.mp = multiprocessing.get_context('spawn')

    def process(self, target, *args):
        process = self.mp.Process(target=target, args=args)
        def cleanup():
            process.join(10)
            if process.is_alive():
                process.terminate(); process.join(5)
        self.addCleanup(cleanup)
        process.start()
        return process

    def test_preloaded_identity_map_cannot_allocate_late_smaller_sequence(self):
        loaded, result = self.mp.Event(), self.mp.Queue()
        with self.db.session() as session:
            device = self.store.locked_device(session, 'account-one', self.device)
            child = self.process(writer, self.url, self.device, loaded, result)
            self.assertTrue(loaded.wait(10))
            self.assertEqual(('preloaded', 0), result.get(timeout=5))
            self.store._put(session, device, common.item(1), 'source')
            # Commit is deliberately later than the competing process's read.
        self.assertEqual(('committed', 2), result.get(timeout=10))
        child.join(5); self.assertEqual(0, child.exitcode)
        with self.db.session() as session:
            rows = session.scalars(select(Change).where(Change.device_id == self.device).order_by(Change.sequence)).all()
            self.assertEqual([(1, 'update-1'), (2, 'update-2')], [(row.sequence, row.update_id) for row in rows])

    def test_first_binding_race_has_one_device_and_one_epoch(self):
        gate, result = self.mp.Event(), self.mp.Queue()
        children = [self.process(requests, self.url, gate, result, 'bind') for _ in range(2)]
        gate.set()
        replies = [result.get(timeout=15) for _ in children]
        self.assertEqual(['bound', 'bound'], [reply[0] for reply in replies])
        self.assertEqual(replies[0][1], replies[1][1])
        with self.db.session() as session:
            self.assertEqual(1, session.get(Installation, 'new-racing-install').epoch)
            self.assertEqual(1, len(session.scalars(select(Device).where(Device.installation_id == 'new-racing-install')).all()))

    def test_rate_limit_is_not_multiplied_by_process_count(self):
        gate, result = self.mp.Event(), self.mp.Queue()
        children = [self.process(requests, self.url, gate, result, 'limit') for _ in range(2)]
        gate.set()
        replies = [result.get(timeout=15) for _ in children]
        self.assertEqual(['limited', 'limited'], [reply[0] for reply in replies])
        codes = [code for _, values in replies for code in values]
        self.assertEqual((10, 10), (codes.count(200), codes.count(429)))
