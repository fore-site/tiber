"""Test the worker-time policy guard and template rendering.

Verify policy rejection and rendered provider content.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from uuid import uuid4

from tiber.application.ports.channel_provider import ProviderResult
from tiber.application.services import (
    DeliveryPolicyGuard,
    NotificationDeliveryProcessor,
    NotificationTemplateResolver,
)
from tiber.domain.entities import (
    DeliveryConstraint,
    Notification,
    Recipient,
    Template,
)
from tiber.domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    NotificationStatus,
)
from tiber.domain.policies import PolicyResolver
from tiber.domain.value_objects import (
    NotificationContent,
    QuietHours,
    RecipientPreferences,
)


class FakeNotificationRepository:
    """In-memory NotificationRepository (get_by_id + save)."""

    def __init__(self) -> None:
        """Initialize an empty store."""
        self._store: dict = {}

    async def get_by_id(self, id, project_id):
        """Get a notification by ID within a project's scope."""
        notification = self._store.get(id)
        if notification is not None and notification.project_id != project_id:
            return None
        return notification

    async def save(self, notification: Notification) -> Notification:
        """Persist a notification by id."""
        self._store[notification.id] = notification
        return notification


class FakeRecipientRepository:
    """In-memory RecipientRepository (get_by_id)."""

    def __init__(self, recipient: Recipient) -> None:
        """Initialize with a single recipient."""
        self._recipient = recipient

    async def get_by_id(self, id, project_id):
        """Return the recipient if id and project scope match."""
        if self._recipient.id != id:
            return None
        if self._recipient.project_id != project_id:
            return None
        return self._recipient


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

    async def get_by_id(self, id, project_id):
        """Return the template if it matches and is project-scoped."""
        if (
            self._template
            and self._template.id == id
            and self._template.project_id == project_id
        ):
            return self._template
        return None


class RecordingProvider:
    """A ChannelProvider that records the payload it was asked to send."""

    name = "recording"

    def __init__(self, channel: DeliveryChannel) -> None:
        """Initialize with a channel and an empty sent list."""
        self.channel = channel
        self.sent: list[tuple] = []

    async def send(
        self,
        recipient_address,
        title,
        body,
        action_url=None,
        image_url=None,
        metadata=None,
    ) -> ProviderResult:
        """Record and succeed."""
        self.sent.append((recipient_address, title, body))
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
    return Notification.create(
        project_id=project_id or uuid4(),
        recipient_id=recipient_id or uuid4(),
        correlation_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.PROMOTIONAL,
        content=NotificationContent(title="Direct", body="Direct body"),
        template_id=template_id,
        template_variables=template_variables,
    )


def build(
    *,
    notification: Notification,
    recipient: Recipient,
    template: Template | None = None,
    guard: DeliveryPolicyGuard,
    constraint_repository=None,
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
        constraint_repository=constraint_repository,
    )
    if template is not None:
        processor_kwargs["template_resolver"] = NotificationTemplateResolver(
            FakeTemplateRepository(template)
        )
    return NotificationDeliveryProcessor(**processor_kwargs), notif_repo, provider


async def test_opt_out_violation_marks_suppressed_without_attempt():
    """A worker-time opt-out violation marks suppressed, records no attempt."""
    notification = make_notification()
    # Opt the recipient out of email so the preference rule rejects.
    recipient = Recipient.reconstitute(
        id=notification.recipient_id,
        project_id=notification.project_id,
        addresses={DeliveryChannel.EMAIL: "a@b.io"},
        preferences=RecipientPreferences(opted_out_channels={DeliveryChannel.EMAIL}),
        external_id=None,
        timezone=None,
        language=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        archived_at=None,
    )
    guard = DeliveryPolicyGuard(PolicyResolver())
    processor, notif_repo, provider = build(
        notification=notification, recipient=recipient, guard=guard
    )
    await notif_repo.save(notification)

    updated = await processor.process(
        notification.id, project_id=notification.project_id
    )

    assert updated.status == NotificationStatus.SUPPRESSED
    assert updated.suppression_reason is not None
    assert "opted out" in updated.suppression_reason
    # No delivery attempt was recorded for a suppression.
    assert provider.sent == []


class StaticConstraintRepository:
    """In-memory DeliveryConstraintRepository holding one fixed constraint."""

    def __init__(self, constraint) -> None:
        """Initialize with the single constraint every lookup returns."""
        self._constraint = constraint

    async def save(self, constraint):
        """Persist (no-op for the static store)."""
        return self._constraint

    async def get_by_project(self, project_id):
        """Return the fixed constraint regardless of project."""
        return self._constraint

    async def load_constraint(self, project_id):
        """Return the fixed constraint for policy evaluation."""
        return self._constraint


async def test_quiet_hours_violation_postpones_with_resume_time():
    """A worker-time quiet-hours violation postpones, setting send_at to resume.

    Fully pinned clock: the notification's send_at (2026-09-15 23:00 UTC)
    falls inside a 22:50-23:10 email window, so the guard must postpone to
    the window end plus the 5-minute grace (23:15). No wall clock, no flake.
    """
    project_id = uuid4()
    send_at = datetime(2026, 9, 15, 23, 0, tzinfo=UTC)
    notification = Notification.create(
        project_id=project_id,
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.PROMOTIONAL,
        content=NotificationContent(title="Hi", body="Hello"),
        send_at=send_at,
    )
    recipient = Recipient.reconstitute(
        id=notification.recipient_id,
        project_id=project_id,
        addresses={DeliveryChannel.EMAIL: "a@b.io"},
        preferences=RecipientPreferences(),
        external_id=None,
        timezone=None,
        language=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        archived_at=None,
    )
    window = QuietHours(
        name="overnight",
        window_start=time(22, 50),
        window_end=time(23, 10),
        channel=DeliveryChannel.EMAIL,
    )
    constraint = DeliveryConstraint.create(
        project_id=project_id,
        quiet_hours=[window],
        timezone="UTC",
    )

    guard = DeliveryPolicyGuard(PolicyResolver())
    processor, notif_repo, provider = build(
        notification=notification,
        recipient=recipient,
        guard=guard,
        constraint_repository=StaticConstraintRepository(constraint),
    )
    await notif_repo.save(notification)

    updated = await processor.process(
        notification.id, project_id=notification.project_id
    )

    assert updated.status == NotificationStatus.POSTPONED
    assert updated.send_at == datetime(2026, 9, 15, 23, 15, tzinfo=UTC)
    # No delivery attempt was recorded for a postponement.
    assert provider.sent == []


async def test_template_content_renders_into_provider_payload():
    """A template renders into the title/body actually sent to the provider."""
    project_id = uuid4()
    template = Template.create(
        project_id=project_id,
        name="welcome",
        channel=DeliveryChannel.EMAIL,
        content=NotificationContent(body="Welcome {{name}}!", title="Hello {{name}}"),
    )
    notification = make_notification(
        project_id=project_id,
        recipient_id=uuid4(),
        template_id=template.id,
        template_variables={"name": "Ada"},
    )
    recipient = Recipient.reconstitute(
        id=notification.recipient_id,
        project_id=project_id,
        addresses={DeliveryChannel.EMAIL: "a@b.io"},
        preferences=RecipientPreferences(),
        external_id=None,
        timezone=None,
        language=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        archived_at=None,
    )
    guard = DeliveryPolicyGuard()  # allows: address present, no blocked channels
    processor, notif_repo, provider = build(
        notification=notification,
        recipient=recipient,
        template=template,
        guard=guard,
    )
    await notif_repo.save(notification)

    updated = await processor.process(
        notification.id, project_id=notification.project_id
    )

    assert updated.status == NotificationStatus.DELIVERED
    assert provider.sent == [("a@b.io", "Hello Ada", "Welcome Ada!")]


async def test_guard_address_rule_rejects_and_skips_delivery():
    """A missing channel address is caught by the guard, not the provider."""
    notification = make_notification()
    recipient = Recipient.reconstitute(
        id=notification.recipient_id,
        project_id=notification.project_id,
        addresses={DeliveryChannel.PUSH: "token"},  # no email address
        preferences=RecipientPreferences(),
        external_id=None,
        timezone=None,
        language=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        archived_at=None,
    )
    guard = DeliveryPolicyGuard(PolicyResolver())
    processor, notif_repo, provider = build(
        notification=notification, recipient=recipient, guard=guard
    )
    await notif_repo.save(notification)

    updated = await processor.process(
        notification.id, project_id=notification.project_id
    )

    assert updated.status == NotificationStatus.SUPPRESSED
    assert "no email address" in updated.suppression_reason
    assert provider.sent == []
