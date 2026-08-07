"""Unit tests for the NotificationDeliveryProcessor use case.

Pure-Python tests using in-memory fakes for the ports and the real
(infrastructure) MockProvider - no database or broker required.
"""

from __future__ import annotations

from uuid import uuid4

from tiber.application.ports.channel_provider import ProviderResult
from tiber.application.services import NotificationDeliveryProcessor
from tiber.domain.entities import Notification, Recipient
from tiber.domain.enums import (
    DeliveryAttemptStatus,
    DeliveryChannel,
    NotificationStatus,
)
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
