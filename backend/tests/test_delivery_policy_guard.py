"""Test the worker-time policy guard and template rendering.

Verify policy rejection and rendered provider content.
"""

from __future__ import annotations

from uuid import uuid4

from tiber.application.ports.channel_provider import ProviderResult
from tiber.application.services import (
    DispatchPolicyGuard,
    InMemoryPreferenceReadModel,
    NotificationDeliveryProcessor,
    NotificationTemplateResolver,
    PolicyResolver,
)
from tiber.domain.entities import Notification, Recipient, Template
from tiber.domain.enums import DeliveryChannel, NotificationStatus
from tiber.domain.value_objects import NotificationContent


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

    async def save(self, attempt):
        """Record a delivery attempt."""
        self.attempts.append(attempt)
        return attempt

    async def list_by_notification(self, notification_id):
        """List attempts for a notification."""
        return [a for a in self.attempts if a.notification_id == notification_id]


class FakeTemplateRepository:
    """In-memory TemplateRepository keyed by id."""

    def __init__(self, template: Template | None = None) -> None:
        """Initialize with an optional single template."""
        self._template = template

    async def get_by_id(self, id):
        """Return the template if it matches."""
        return self._template if self._template and self._template.id == id else None


class RecordingProvider:
    """A ChannelProvider that records the payload it was asked to send."""

    name = "recording"

    def __init__(self, channel: DeliveryChannel) -> None:
        """Initialize with a channel and an empty sent list."""
        self.channel = channel
        self.sent: list[tuple] = []

    async def send(
        self, recipient_address, subject, body, metadata=None
    ) -> ProviderResult:
        """Record and succeed."""
        self.sent.append((recipient_address, subject, body))
        return ProviderResult(success=True, provider_message_id="p-1")

    async def health_check(self) -> bool:
        """Return True."""
        return True


def make_notification(
    *,
    template_id=None,
    template_variables=None,
    project_id=None,
    recipient_id=None,
) -> Notification:
    """Build a pending email notification with sensible defaults."""
    return Notification(
        id=uuid4(),
        project_id=project_id or uuid4(),
        recipient_id=recipient_id or uuid4(),
        correlation_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        content=NotificationContent(subject="Direct", body="Direct body"),
        template_id=template_id,
        template_variables=template_variables,
    )


def build(
    *,
    notification: Notification,
    recipient: Recipient,
    template: Template | None = None,
    guard: DispatchPolicyGuard,
) -> tuple[
    NotificationDeliveryProcessor, FakeNotificationRepository, RecordingProvider
]:
    """Build a processor with fakes, guard, and (optionally) template resolver."""
    notif_repo = FakeNotificationRepository()
    provider = RecordingProvider(DeliveryChannel.EMAIL)
    processor_kwargs = dict(
        notification_repository=notif_repo,
        recipient_repository=FakeRecipientRepository(recipient),
        delivery_attempt_repository=FakeDeliveryAttemptRepository(),
        provider=provider,
        policy_guard=guard,
    )
    if template is not None:
        processor_kwargs["template_resolver"] = NotificationTemplateResolver(
            FakeTemplateRepository(template)
        )
    return NotificationDeliveryProcessor(**processor_kwargs), notif_repo, provider


async def test_policy_violation_marks_policy_rejected_without_attempt():
    """A worker-time policy rejection marks policy_rejected, records no attempt."""
    notification = make_notification()
    recipient = Recipient(
        id=notification.recipient_id,
        project_id=notification.project_id,
        addresses={"email": "a@b.io"},
    )
    # Block the recipient's email channel so the preference rule rejects.
    guard = DispatchPolicyGuard(
        PolicyResolver(
            preferences=InMemoryPreferenceReadModel(
                {recipient.id: frozenset({DeliveryChannel.EMAIL})}
            )
        )
    )
    processor, notif_repo, provider = build(
        notification=notification, recipient=recipient, guard=guard
    )
    await notif_repo.save(notification)

    updated = await processor.process(notification.id)

    assert updated.status == NotificationStatus.POLICY_REJECTED
    assert updated.policy_violation_reason is not None
    assert "opted out" in updated.policy_violation_reason
    # No delivery attempt was recorded for a policy rejection.
    assert provider.sent == []


async def test_template_content_renders_into_provider_payload():
    """A template renders into the subject/body actually sent to the provider."""
    project_id = uuid4()
    template = Template(
        id=uuid4(),
        project_id=project_id,
        name="welcome",
        slug="welcome",
        channel=DeliveryChannel.EMAIL,
        body="Welcome {{name}}!",
        subject="Hello {{name}}",
    )
    notification = make_notification(
        project_id=project_id,
        recipient_id=uuid4(),
        template_id=template.id,
        template_variables={"name": "Ada"},
    )
    recipient = Recipient(
        id=notification.recipient_id,
        project_id=project_id,
        addresses={"email": "a@b.io"},
    )
    guard = DispatchPolicyGuard()  # allows: address present, no blocked channels
    processor, notif_repo, provider = build(
        notification=notification,
        recipient=recipient,
        template=template,
        guard=guard,
    )
    await notif_repo.save(notification)

    updated = await processor.process(notification.id)

    assert updated.status == NotificationStatus.DELIVERED
    assert provider.sent == [("a@b.io", "Hello Ada", "Welcome Ada!")]


async def test_guard_address_rule_rejects_and_skips_delivery():
    """A missing channel address is caught by the guard, not the provider."""
    notification = make_notification()
    recipient = Recipient(
        id=notification.recipient_id,
        project_id=notification.project_id,
        addresses={"push": "token"},  # no email address
    )
    guard = DispatchPolicyGuard(PolicyResolver())
    processor, notif_repo, provider = build(
        notification=notification, recipient=recipient, guard=guard
    )
    await notif_repo.save(notification)

    updated = await processor.process(notification.id)

    assert updated.status == NotificationStatus.POLICY_REJECTED
    assert "no email address" in updated.policy_violation_reason
    assert provider.sent == []
