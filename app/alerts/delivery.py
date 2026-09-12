"""Non-blocking alert delivery channels (M11-T08).

The alert engine remains responsible for producing an event snapshot.  This
module is a small delivery boundary: publishing an event only schedules
background work and therefore cannot hold up event generation.  Real external
providers are deliberately not implemented; the e-mail, SMS and enterprise IM
adapters are local fakes behind the same interface and accept credentials via a
callable injection point.

Credentials are never copied into an event, result, log message or repr.  A
future provider can replace one of the fake adapters without changing the
engine or the WebSocket contracts.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence


Event = Mapping[str, Any]
CredentialProvider = Callable[[], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]


class DeliveryChannel(Protocol):
    """Minimal interface implemented by every delivery channel."""

    name: str

    async def send(self, event: Event) -> None:
        ...


class DeliveryError(RuntimeError):
    """An adapter rejected a delivery attempt."""


class _SubscriberChannel:
    """Bounded in-process fan-out channel used by WebSocket consumers."""

    def __init__(self, name: str, *, queue_size: int = 64) -> None:
        self.name = name
        self.queue_size = max(1, int(queue_size))
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def send(self, event: Event) -> None:
        # Make a shallow JSON-safe snapshot at the boundary.  The event passed
        # to the engine is never mutated by a consumer.
        payload = dict(event)
        async with self._lock:
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            # Latest-only behavior is preferable to blocking the producer when
            # a browser or App has gone stale.
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class ManagementPageChannel(_SubscriberChannel):
    """Real-time management page event stream."""

    def __init__(self, *, queue_size: int = 64) -> None:
        super().__init__("management", queue_size=queue_size)


class AppNotificationChannel(_SubscriberChannel):
    """Closed-app in-product notification stream (separate from detections)."""

    def __init__(self, *, queue_size: int = 64) -> None:
        super().__init__("app", queue_size=queue_size)


class LocalExternalAdapter:
    """Base class for a local fake external provider.

    ``credential_provider`` is called only when sending.  The returned mapping
    is intentionally not retained, stringified or included in the result.  A
    test can set ``failures_before_success`` to exercise retry behavior.
    """

    def __init__(
        self,
        name: str,
        *,
        credential_provider: CredentialProvider | None = None,
        credentials_provider: CredentialProvider | None = None,
        failures_before_success: int = 0,
    ) -> None:
        self.name = name
        self.credential_provider = credential_provider or credentials_provider
        self.failures_before_success = max(0, int(failures_before_success))
        self.sent_events: list[dict[str, Any]] = []
        self.attempts = 0

    async def send(self, event: Event) -> None:
        self.attempts += 1
        if self.credential_provider is not None:
            supplied = self.credential_provider()
            if inspect.isawaitable(supplied):
                supplied = await supplied
            # Validate that injection is callable/configured without exposing
            # any value.  Providers may return an empty mapping for local use.
            if supplied is None or not isinstance(supplied, Mapping):
                raise DeliveryError("credential provider returned invalid configuration")
        if self.failures_before_success:
            self.failures_before_success -= 1
            raise DeliveryError(f"{self.name} local adapter rejected delivery")
        self.sent_events.append(dict(event))

    async def deliver(self, event: Event) -> None:
        """Provider-friendly alias for :meth:`send`."""
        await self.send(event)


class EmailAdapter(LocalExternalAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("email", **kwargs)


class SmsAdapter(LocalExternalAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("sms", **kwargs)


class EnterpriseIMAdapter(LocalExternalAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("enterprise_im", **kwargs)


# Deliberately no WebhookAdapter: callbacks to upstream systems are outside
# M11-T08 and must not accidentally be enabled by configuration.

# Descriptive aliases keep the public boundary convenient for integrations
# that call providers "channels" rather than "adapters".
EmailChannel = EmailAdapter
SmsChannel = SmsAdapter
EnterpriseIMChannel = EnterpriseIMAdapter
FakeEmailAdapter = EmailAdapter
FakeSmsAdapter = SmsAdapter
FakeEnterpriseIMAdapter = EnterpriseIMAdapter


@dataclass(frozen=True)
class DeliveryReceipt:
    delivery_id: str
    channel: str
    status: str
    attempts: int
    error_code: str | None = None


@dataclass
class _PendingDelivery:
    delivery_id: str
    channel: DeliveryChannel
    event: dict[str, Any]
    task: asyncio.Task[DeliveryReceipt] | None = field(default=None)


class AlertDeliveryService:
    """Fan-out dispatcher with bounded retries and no producer blocking."""

    DEFAULT_CHANNELS = ("management", "app", "email", "sms", "enterprise_im")

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.05,
        channels: Mapping[str, DeliveryChannel] | None = None,
    ) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        builtins: dict[str, DeliveryChannel] = {
            "management": ManagementPageChannel(),
            "app": AppNotificationChannel(),
            "email": EmailAdapter(),
            "sms": SmsAdapter(),
            "enterprise_im": EnterpriseIMAdapter(),
        }
        if channels:
            builtins.update(channels)
        self.channels = builtins
        self._pending: set[asyncio.Task[DeliveryReceipt]] = set()
        self.last_receipts: list[DeliveryReceipt] = []

    def dispatch(
        self,
        event: Event,
        channels: Sequence[str] | None = None,
    ) -> list[str]:
        """Schedule delivery and return immediately with delivery IDs.

        Unknown channels are rejected synchronously as a configuration error;
        adapter failures are asynchronous and become ``failed`` receipts after
        the retry budget is exhausted.
        """
        aliases = {"admin": "management", "management_page": "management", "in_app": "app",
                   "enterprise-im": "enterprise_im", "enterpriseIM": "enterprise_im", "im": "enterprise_im"}
        selected = tuple(aliases.get(str(name), str(name)) for name in (channels or self.DEFAULT_CHANNELS))
        unknown = [name for name in selected if name not in self.channels]
        if unknown:
            raise ValueError(f"unsupported delivery channel(s): {', '.join(unknown)}")
        if hasattr(event, "to_mapping"):
            event = event.to_mapping()  # type: ignore[assignment]
        snapshot = dict(event)
        ids: list[str] = []
        for name in selected:
            delivery_id = f"del-{uuid.uuid4().hex[:16]}"
            ids.append(delivery_id)
            task = asyncio.create_task(self._deliver(delivery_id, self.channels[name], snapshot))
            self._pending.add(task)
            task.add_done_callback(self._on_done)
        return ids

    # Naming used by event producers and makes the non-blocking contract clear.
    publish = dispatch

    submit = dispatch
    deliver_event = dispatch
    publish_event = dispatch

    async def _deliver(
        self,
        delivery_id: str,
        channel: DeliveryChannel,
        event: dict[str, Any],
    ) -> DeliveryReceipt:
        attempts = 0
        error_code: str | None = None
        while attempts < self.max_attempts:
            attempts += 1
            try:
                await channel.send(event)
                receipt = DeliveryReceipt(delivery_id, channel.name, "delivered", attempts)
                self.last_receipts.append(receipt)
                return receipt
            except asyncio.CancelledError:
                raise
            except Exception:
                # Keep exception details out of API/log payloads: providers may
                # include URLs or credential-bearing messages.
                error_code = "adapter_failure"
                if attempts < self.max_attempts:
                    await asyncio.sleep(self.retry_delay_seconds * (2 ** (attempts - 1)))
        receipt = DeliveryReceipt(delivery_id, channel.name, "failed", attempts, error_code)
        self.last_receipts.append(receipt)
        return receipt

    def _on_done(self, task: asyncio.Task[DeliveryReceipt]) -> None:
        self._pending.discard(task)
        # Receipt is already retained by _deliver; retrieve exceptions only to
        # avoid asyncio's "Task exception was never retrieved" warning.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.result()

    async def drain(self) -> list[DeliveryReceipt]:
        """Wait for currently scheduled deliveries, primarily for tests/shutdown."""
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
        return list(self.last_receipts)

    async def close(self) -> None:
        for task in tuple(self._pending):
            task.cancel()
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
        self._pending.clear()


# Stable aliases for callers that prefer the shorter names.
AlertDispatcher = AlertDeliveryService
ManagementWebSocketChannel = ManagementPageChannel


__all__ = [
    "AlertDeliveryService", "AlertDispatcher", "DeliveryChannel", "DeliveryError",
    "DeliveryReceipt", "ManagementPageChannel", "ManagementWebSocketChannel",
    "AppNotificationChannel", "EmailAdapter", "SmsAdapter", "EnterpriseIMAdapter",
    "EmailChannel", "SmsChannel", "EnterpriseIMChannel", "FakeEmailAdapter",
    "FakeSmsAdapter", "FakeEnterpriseIMAdapter", "LocalExternalAdapter",
]
