"""Unit tests for the NotificationDeliveryProcessor use case.

Pure-Python tests using in-memory fakes for the ports and the real
(infrastructure) MockProvider - no database or broker required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tiber.application.ports.channel_provider import ProviderResult
from tiber.application.services import NotificationDeliveryProcessor
from tiber.domain.entities import Notification, Recipient
from tiber.domain.enums import (
    DeliveryAttemptStatus,
    DeliveryChannel,
    NotificationStatus,
    SendTimeBasis,
)
from tiber.domain.exceptions import InvalidStateTransitionError
from tiber.domain.value_objects import NotificationContent
from tiber.infrastructure.providers.mock import MockProvider


class FakeNotificationRepository:
    """In-memory NotificationRepository (get_by_id + save)."""

    def __init__(self) -> None:
        """Initialize an empty store."""
        self._store: dict = {}

    async def get_by_id(self, id):
        """Get a notification by ID."""
        return self._store.get(id)

    async def save(self, notification: Notification) -> Notification:
        """Persist a notification by id."""
        self._store[notification.id] = notification
        return notification


class FakeRecipientRepository:
    """In-memory RecipientRepository (get_by_id)."""

    def __init__(self, recipient: Recipient) -> None:
        """Initialize with a single recipient."""
        self._recipient = recipient

    async def get_by_id(self, id):
        """Return the recipient if the id matches."""
        return self._recipient if self._recipient.id == id else None


class FakeDeliveryAttemptRepository:
    """In-memory DeliveryAttemptRepository."""

    def __init__(self) -> None:
        """Initialize an empty attempt list."""
        self.attempts = []

    async def save(self, attempt) -> object:
        """Record a delivery attempt."""
        self.attempts.append(attempt)
        return attempt

    async def list_by_notification(self, notification_id):
        """List attempts for a notification."""
        return [a for a in self.attempts if a.notification_id == notification_id]


class FailingProvider:
    """A ChannelProvider that always fails."""

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "always_fail"

    @property
    def channel(self) -> DeliveryChannel:
        """Return the supported channel."""
        return DeliveryChannel.EMAIL

    async def send(
        self, recipient_address, subject, body, metadata=None
    ) -> ProviderResult:
        """Return a failed result."""
        return ProviderResult(success=False, error_message="provider down")

    async def health_check(self) -> bool:
        """Return False."""
        return False


def make_notification() -> Notification:
    """Build a pending email notification."""
    return Notification(
        id=uuid4(),
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        content=NotificationContent(subject="Hi", body="Hello"),
    )


def make_recipient(notification: Notification, addresses: dict) -> Recipient:
    """Build a recipient that belongs to the notification."""
    return Recipient(
        id=notification.recipient_id,
        project_id=notification.project_id,
        addresses=addresses,
    )


def build(recipient, provider=None):
    """Build a processor wired to fakes plus its notification repo and attempts."""
    notif_repo = FakeNotificationRepository()
    attempts = FakeDeliveryAttemptRepository()
    processor = NotificationDeliveryProcessor(
        notification_repository=notif_repo,
        recipient_repository=FakeRecipientRepository(recipient),
        delivery_attempt_repository=attempts,
        provider=provider or MockProvider(DeliveryChannel.EMAIL),
    )
    return processor, notif_repo, attempts


async def test_success_marks_delivered_and_records_attempt():
    """A successful send records a succeeded attempt and delivers."""
    notification = make_notification()
    recipient = make_recipient(notification, {"email": "a@b.io"})
    processor, notif_repo, attempts = build(recipient)

    await notif_repo.save(notification)
    updated = await processor.process(notification.id)

    assert updated.status == NotificationStatus.DELIVERED
    assert updated.delivered_at is not None
    assert len(attempts.attempts) == 1
    assert attempts.attempts[0].status == DeliveryAttemptStatus.SUCCEEDED
    assert attempts.attempts[0].provider_message_id is not None


async def test_failure_marks_failed_and_records_failed_attempt():
    """A failed send marks the notification failed and records the error."""
    notification = make_notification()
    recipient = make_recipient(notification, {"email": "a@b.io"})
    processor, notif_repo, attempts = build(recipient, provider=FailingProvider())

    await notif_repo.save(notification)
    updated = await processor.process(notification.id)

    assert updated.status == NotificationStatus.FAILED
    assert attempts.attempts[0].status == DeliveryAttemptStatus.FAILED
    assert attempts.attempts[0].error == "provider down"


async def test_missing_channel_address_marks_failed():
    """A notification whose recipient lacks the channel address fails."""
    notification = make_notification()  # email
    recipient = make_recipient(notification, {"push": "token"})  # no email address
    processor, notif_repo, attempts = build(recipient)

    await notif_repo.save(notification)
    updated = await processor.process(notification.id)

    assert updated.status == NotificationStatus.FAILED
    assert attempts.attempts[0].status == DeliveryAttemptStatus.FAILED
    assert "no email address" in attempts.attempts[0].error


async def test_terminal_notification_is_not_redispatched():
    """A notification already delivered is not dispatched again."""
    notification = make_notification().mark_delivered()
    recipient = make_recipient(notification, {"email": "a@b.io"})
    processor, notif_repo, attempts = build(recipient)

    await notif_repo.save(notification)
    updated = await processor.process(notification.id)

    assert updated.status == NotificationStatus.DELIVERED
    assert attempts.attempts == []


# ---------------------------------------------------------------------------
# Scheduling / state-machine behaviour
# ---------------------------------------------------------------------------


class SpyingProvider(MockProvider):
    """A MockProvider that counts send() invocations."""

    def __init__(self) -> None:
        """Initialize the spy around a mock email provider."""
        super().__init__(DeliveryChannel.EMAIL)
        self.send_count = 0

    async def send(self, recipient_address, subject, body, metadata=None):
        """Count the call, then delegate to the mock provider."""
        self.send_count += 1
        return await super().send(recipient_address, subject, body, metadata=metadata)


def make_scheduled_notification(scheduled_at: datetime) -> Notification:
    """Build a pending, explicitly-scheduled email notification."""
    base = make_notification()
    return Notification(
        id=base.id,
        project_id=base.project_id,
        recipient_id=base.recipient_id,
        correlation_id=base.correlation_id,
        channel=base.channel,
        content=base.content,
        scheduled_at=scheduled_at,
        send_time_basis=SendTimeBasis.EXPLICIT,
    )


async def test_future_scheduled_notification_is_not_delivered_early():
    """A PENDING notification scheduled in the future stays PENDING and is untouched.

    No provider send and no delivery attempt happen before scheduled_at, so the
    caller can defer (requeue with a countdown) while preserving idempotency.
    """
    notification = make_scheduled_notification(datetime.now(UTC) + timedelta(hours=1))
    recipient = make_recipient(notification, {"email": "a@b.io"})

    provider = SpyingProvider()
    processor, notif_repo, attempts = build(recipient, provider=provider)
    await notif_repo.save(notification)

    updated = await processor.process(notification.id)

    assert updated.status == NotificationStatus.PENDING
    assert updated.scheduled_at == notification.scheduled_at
    assert provider.send_count == 0
    assert attempts.attempts == []


async def test_scheduled_notification_delivers_once_due():
    """A notification whose scheduled time has passed is delivered normally."""
    notification = make_scheduled_notification(datetime.now(UTC) - timedelta(seconds=5))
    recipient = make_recipient(notification, {"email": "a@b.io"})
    processor, notif_repo, attempts = build(recipient)

    await notif_repo.save(notification)
    updated = await processor.process(notification.id)

    assert updated.status == NotificationStatus.DELIVERED
    assert updated.delivered_at is not None
    assert len(attempts.attempts) == 1
    assert attempts.attempts[0].status == DeliveryAttemptStatus.SUCCEEDED


async def test_concurrent_redispatch_is_idempotent():
    """A second dispatch of the same id after delivery does not re-send."""
    notification = make_notification()
    recipient = make_recipient(notification, {"email": "a@b.io"})

    provider = SpyingProvider()
    processor, notif_repo, attempts = build(recipient, provider=provider)
    await notif_repo.save(notification)

    first = await processor.process(notification.id)
    second = await processor.process(notification.id)

    assert first.status == NotificationStatus.DELIVERED
    assert second.status == NotificationStatus.DELIVERED
    assert provider.send_count == 1
    assert len(attempts.attempts) == 1


async def test_processing_state_machine_transitions():
    """PROCESSING is the transient in-flight state: pending -> processing -> terminal."""
    notification = make_notification()

    processing = notification.mark_processing()
    assert processing.status == NotificationStatus.PROCESSING

    delivered = processing.mark_delivered()
    assert delivered.status == NotificationStatus.DELIVERED

    failed = notification.mark_processing().mark_failed()
    assert failed.status == NotificationStatus.FAILED


async def test_processing_transition_is_invalid_from_terminal_state():
    """A delivered notification cannot move back into PROCESSING."""
    delivered = make_notification().mark_delivered()
    with pytest.raises(InvalidStateTransitionError):
        delivered.mark_processing()


async def test_delivered_transition_rejected_from_processing_duplicate():
    """mark_delivered is only valid from pending/processing, not terminal states."""
    cancelled = make_notification().mark_cancelled()
    with pytest.raises(InvalidStateTransitionError):
        cancelled.mark_delivered()
