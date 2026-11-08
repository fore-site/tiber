from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tiber.application.ports.channel_provider import ProviderResult
from tiber.application.services.delivery import NotificationDeliveryProcessor
from tiber.domain.entities import Notification, Recipient
from tiber.domain.enums import (
    DeliveryAttemptStatus,
    DeliveryChannel,
    NotificationCategory,
    NotificationStatus,
    SendTimeBasis,
)
from tiber.domain.value_objects import (
    ContentAction,
    ContentImage,
    NotificationContent,
    RecipientPreferences,
)


class _UnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None


class _Notifications:
    def __init__(self, notification):
        self.notification = notification

    async def get_by_id(self, notification_id, project_id):
        if (
            notification_id == self.notification.id
            and project_id == self.notification.project_id
        ):
            return self.notification
        return None

    async def claim_for_delivery(
        self, notification, *, expected_status, stale_before=None
    ):
        if self.notification.status is not expected_status:
            return False
        if stale_before is not None and self.notification.updated_at > stale_before:
            return False
        self.notification = notification
        return True

    async def save(self, notification):
        self.notification = notification
        return notification


class _Recipients:
    def __init__(self, recipient):
        self.recipient = recipient

    async def get_by_id(self, recipient_id, project_id):
        return self.recipient


class _Attempts:
    def __init__(self):
        self.saved = []

    async def save(self, attempt):
        self.saved.append(attempt)
        return attempt


class _Provider:
    channel = DeliveryChannel.EMAIL
    name = "recording"

    def __init__(self, *, failure=None):
        self.calls = []
        self.failure = failure

    async def send(
        self,
        recipient_address,
        title,
        body,
        actions=(),
        images=(),
        metadata=None,
        html_body=None,
    ):
        self.calls.append(
            {
                "recipient_address": recipient_address,
                "title": title,
                "body": body,
                "actions": actions,
                "images": images,
                "html_body": html_body,
                "metadata": metadata,
            }
        )
        if self.failure:
            raise self.failure
        return ProviderResult(success=True, provider_message_id="provider-id")

    async def health_check(self):
        return True


def _processor(*, provider):
    project_id = uuid4()
    recipient_id = uuid4()
    action = ContentAction(label="Open", url="https://example.test/action")
    image = ContentImage(url="https://example.test/image.png", alt="image")
    notification = Notification.create(
        project_id=project_id,
        recipient_id=recipient_id,
        transaction_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.INFORMATIONAL,
        content=NotificationContent(
            title="Subject",
            plain_text_body="Message",
            actions=(action,),
            images=(image,),
        ),
        send_time_basis=SendTimeBasis.IMMEDIATE,
    )
    recipient = Recipient.create(
        project_id=project_id,
        addresses={DeliveryChannel.EMAIL: "person@example.test"},
        preferences=RecipientPreferences(),
    )
    notifications = _Notifications(notification)
    attempts = _Attempts()
    return (
        NotificationDeliveryProcessor(
            unit_of_work=_UnitOfWork(),
            notification_repository=notifications,
            recipient_repository=_Recipients(recipient),
            delivery_attempt_repository=attempts,
            provider=provider,
        ),
        notification,
        notifications,
        attempts,
        action,
        image,
    )


async def test_delivery_passes_structured_content_to_provider():
    """The provider receives actions and images through the shared contract."""
    provider = _Provider()
    processor, notification, notifications, attempts, action, image = _processor(
        provider=provider
    )

    updated = await processor.process(
        notification.id,
        project_id=notification.project_id,
    )

    assert updated.status is NotificationStatus.DELIVERED
    assert notifications.notification.status is NotificationStatus.DELIVERED
    assert attempts.saved[0].status is DeliveryAttemptStatus.SUCCESS
    assert provider.calls[0]["actions"] == (action,)
    assert provider.calls[0]["images"] == (image,)
    assert provider.calls[0]["body"] == "Message"


async def test_provider_exception_records_attempt_and_releases_for_retry():
    """A provider exception is recorded and leaves the notification retryable."""
    provider = _Provider(failure=RuntimeError("temporary network failure"))
    processor, notification, notifications, attempts, _, _ = _processor(
        provider=provider
    )

    with pytest.raises(RuntimeError, match="temporary network failure"):
        await processor.process(
            notification.id,
            project_id=notification.project_id,
        )

    assert notifications.notification.status is NotificationStatus.PENDING
    assert attempts.saved[0].status is DeliveryAttemptStatus.FAIL


async def test_active_processing_lease_does_not_send_twice():
    """A duplicate worker defers while another worker still owns the lease."""
    provider = _Provider()
    processor, notification, notifications, attempts, _, _ = _processor(
        provider=provider
    )
    active = replace(
        notifications.notification,
        status=NotificationStatus.PROCESSING,
        updated_at=datetime.now(UTC),
    )
    notifications.notification = active

    updated = await processor.process(
        notification.id,
        project_id=notification.project_id,
    )

    assert updated.status is NotificationStatus.PROCESSING
    assert provider.calls == []
    assert attempts.saved == []


async def test_expired_processing_lease_can_be_reclaimed():
    """A replacement worker can recover processing left by a dead worker."""
    provider = _Provider()
    processor, notification, notifications, attempts, _, _ = _processor(
        provider=provider
    )
    stale = replace(
        notifications.notification,
        status=NotificationStatus.PROCESSING,
        updated_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    notifications.notification = stale

    updated = await processor.process(
        notification.id,
        project_id=notification.project_id,
    )

    assert updated.status is NotificationStatus.DELIVERED
    assert len(provider.calls) == 1
    assert attempts.saved[0].status is DeliveryAttemptStatus.SUCCESS
