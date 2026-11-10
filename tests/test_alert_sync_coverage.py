"""M32-T24: characterize WS gaps before permitting slower REST recovery.

Uses real delivery/runtime/store code with explicit memory stores, no app.main,
application lifespan, database, provider, image or filesystem writes. Passing
these tests proves the gaps exist, NOT that full WS coverage passed.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.alerts.delivery import AlertDeliveryService, ManagementPageChannel
from app.alerts.disposition import AlertDispositionStore
from app.alerts.runtime import ServerAlertRuntime


class AlertSyncCoverageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = AlertDispositionStore(database_manager=None)
        self.channel = ManagementPageChannel(queue_size=2)
        self.delivery = AlertDeliveryService(channels={"management": self.channel}, database_manager=None)
        self.project = "m32-t24-memory"

    def persist(self, identity):
        return self.store.register({"eventId": identity, "state": "CONFIRMED",
            "confirmedAtUs": 123, "severity": "MAJOR"}, project_id=self.project)

    async def test_policy_can_hide_durable_events_from_connected_management_subscriber(self):
        queue = await self.channel.subscribe(self.project)
        for index, values in enumerate([
            dict(enabled=False, channels=["management"], minimumSeverity="MINOR"),
            dict(enabled=True, channels=["app"], minimumSeverity="MINOR"),
            dict(enabled=True, channels=["management"], minimumSeverity="CRITICAL"),
        ]):
            with self.subTest(policy=values):
                self.delivery.policy_store.save(self.project, values, index)
                event = self.persist(f"filtered-{index}")
                self.assertEqual(self.delivery.dispatch(event, ["management"], project_id=self.project), [])
                await self.delivery.drain()
                self.assertTrue(queue.empty())
                self.assertIn(event["eventId"], [item["eventId"] for item in self.store.list(project_id=self.project)])
        self.assertEqual(self.channel.subscriber_count, 1)

    async def test_slow_subscriber_loses_older_events_but_rest_source_keeps_all(self):
        queue = await self.channel.subscribe(self.project)
        for identity in ("one", "two", "three"):
            self.delivery.dispatch(self.persist(identity), ["management"], project_id=self.project)
        await self.delivery.drain()
        self.assertEqual([queue.get_nowait()["eventId"] for _ in range(queue.qsize())], ["two", "three"])
        self.assertEqual({item["eventId"] for item in self.store.list(project_id=self.project)}, {"one", "two", "three"})

    async def test_reconnect_has_no_replay_and_another_project_cannot_receive_event(self):
        old = await self.channel.subscribe(self.project)
        other = await self.channel.subscribe("different-project")
        await self.channel.unsubscribe(old)
        self.delivery.dispatch(self.persist("offline"), ["management"], project_id=self.project)
        await self.delivery.drain()
        restored = await self.channel.subscribe(self.project)
        self.assertTrue(restored.empty())
        self.assertTrue(other.empty())
        self.assertEqual(self.store.list(project_id=self.project)[0]["eventId"], "offline")
        self.assertEqual(self.store.list(project_id="different-project"), [])

    async def test_subscribers_are_process_local_not_a_cross_worker_change_stream(self):
        another_worker = ManagementPageChannel()
        queue = await another_worker.subscribe(self.project)
        self.delivery.dispatch(self.persist("worker-a"), ["management"], project_id=self.project)
        await self.delivery.drain()
        self.assertTrue(queue.empty())

    async def test_server_runtime_broadcasts_confirmation_but_not_end_transition(self):
        queue = await self.channel.subscribe(self.project)
        profile = {"revision": 1, "alertRules": [{"enabled": True, "rawLabel": "head",
            "camera": {"minimumConfidence": .5, "minimumConsecutiveFrames": 1}}]}
        runtime = ServerAlertRuntime(lambda identity: {"version": "1"},
            SimpleNamespace(get=lambda *args, **kwargs: profile), self.store, self.delivery, Path("unused-no-frame"))
        detected = SimpleNamespace(model_id="fixture", detections=[SimpleNamespace(
            to_alert_detection=lambda: {"label": "head", "confidence": .9})])
        event = runtime.process(source_id="camera", captured_at_us=100, result=detected, project_id=self.project)[0]
        await self.delivery.drain()
        self.assertEqual(queue.get_nowait()["state"], "CONFIRMED")
        runtime.process(source_id="camera", captured_at_us=200,
            result=SimpleNamespace(model_id="fixture", detections=[]), project_id=self.project)
        await self.delivery.drain()
        self.assertTrue(queue.empty())
        self.assertEqual(self.store.get(event["eventId"], self.project)["state"], "ENDED")


if __name__ == "__main__":
    unittest.main()
