import asyncio
import unittest

from app.alerts.delivery import (
    AlertDeliveryService,
    AppNotificationChannel,
    EmailAdapter,
    EnterpriseIMAdapter,
    ManagementPageChannel,
    SmsAdapter,
)


class AlertDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_management_and_app_channels_are_independent(self):
        management = ManagementPageChannel()
        app = AppNotificationChannel()
        service = AlertDeliveryService(
            channels={"management": management, "app": app}, retry_delay_seconds=0
        )
        management_queue = await management.subscribe()
        app_queue = await app.subscribe()
        ids = service.dispatch({"eventId": "evt-1", "severity": "MAJOR"}, ["management", "app"])
        self.assertEqual(len(ids), 2)
        await service.drain()
        self.assertEqual((await management_queue.get())["eventId"], "evt-1")
        self.assertEqual((await app_queue.get())["eventId"], "evt-1")
        self.assertEqual(management.subscriber_count, 1)
        self.assertEqual(app.subscriber_count, 1)

    async def test_external_adapters_use_injected_credentials_without_exposing_them(self):
        secret = "do-not-log"
        seen = []

        def credentials():
            seen.append(True)
            return {"api_key": secret}

        adapters = [
            EmailAdapter(credential_provider=credentials),
            SmsAdapter(credential_provider=credentials),
            EnterpriseIMAdapter(credential_provider=credentials),
        ]
        for adapter in adapters:
            await adapter.send({"eventId": "evt-2"})
            self.assertEqual(adapter.sent_events, [{"eventId": "evt-2"}])
            self.assertNotIn(secret, repr(adapter.sent_events))
        self.assertEqual(len(seen), 3)

    async def test_failures_retry_with_a_hard_upper_bound_and_do_not_raise(self):
        adapter = SmsAdapter(failures_before_success=10)
        service = AlertDeliveryService(
            channels={"sms": adapter}, max_attempts=3, retry_delay_seconds=0
        )
        # dispatch is deliberately not awaited: producer receives an id first.
        ids = service.dispatch({"eventId": "evt-3"}, ["sms"])
        self.assertEqual(len(ids), 1)
        receipts = await service.drain()
        self.assertEqual(adapter.attempts, 3)
        self.assertEqual(receipts[-1].status, "failed")
        self.assertEqual(receipts[-1].attempts, 3)
        self.assertEqual(receipts[-1].error_code, "adapter_failure")

    async def test_unknown_webhook_channel_is_rejected(self):
        service = AlertDeliveryService()
        with self.assertRaises(ValueError):
            service.dispatch({"eventId": "evt-4"}, ["webhook"])


if __name__ == "__main__":
    unittest.main()
