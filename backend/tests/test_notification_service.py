"""Unit tests for the NotificationService use case.

Pure-Python tests using in-memory fakes for the ports (idempotency guard,
repositories, publisher) - no database or broker required. The intake-time
template resolution and policy resolution use the real collaborator services
with in-memory repositories, matching production wiring.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from tiber.application.services import (
    NotificationService,
    NotificationTemplateResolver,
    PolicyResolver,
)
from tiber.domain.entities import Recipient, Template
from tiber.domain.enums import DeliveryChannel, NotificationStatus
from tiber.domain.exceptions import (
    ProjectScopeViolationError,
    RecipientNotFoundError,
    TemplateChannelMismatchError,
)


class FakeIdempotency:
    """In-memory IdempotencyGuard."""

    def __init__(self) -> None:
        """Initialize an empty key store."""
        self._store: dict[tuple[UUID, str], UUID] = {}

    async def check_and_store(
        self, project_id: UUID, key: str, notification_id: UUID
    ) -> bool:
        """Atomically store a key; True if newly stored."""
        map_key = (project_id, key)
        if map_key in self._store:
            return False
        self._store[map_key] = notification_id
        return True

    async def get_existing_notification_id(
        self, project_id: UUID, key: str
    ) -> UUID | None:
        """Return the stored notification ID for a key, if any."""
        return self._store.get((project_id, key))


class FakeRepository:
    """In-memory NotificationRepository."""

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._store: dict[UUID, object] = {}

    async def save(self, notification) -> object:
        """Persist a notification."""
        self._store[notification.id] = notification
        return notification

    async def get_by_id(self, id: UUID):
        """Get a notification by ID."""
        return self._store.get(id)

    async def get_by_idempotency_key(self, project_id: UUID, key: str):
        """Get a notification by project and idempotency key."""
        for n in self._store.values():
            if n.project_id == project_id and n.idempotency_key == key:
                return n
        return None

    async def list_by_project(self, project_id: UUID, limit: int, offset: int):
        """List notifications for a project with pagination."""
        items = [n for n in self._store.values() if n.project_id == project_id]
        return items[offset : offset + limit]


class FakeRecipientRepository:
    """In-memory RecipientRepository backed by a mapping by id."""

    def __init__(self, recipients: dict | None = None) -> None:
        """Initialize the store."""
        self._store = recipients or {}

    async def get_by_id(self, id: UUID):
        """Get a recipient by ID."""
        return self._store.get(id)


class FakeTemplateRepository:
    """In-memory TemplateRepository backed by a mapping of templates."""

    def __init__(self, templates: dict | None = None) -> None:
        """Initialize the store."""
        self._store = templates or {}

    async def get_by_id(self, id: UUID):
        """Get a template by ID."""
        return self._store.get(id)


class FakePublisher:
    """In-memory MessagePublisher."""

    def __init__(self) -> None:
        """Initialize an empty published list."""
        self.published: list[UUID] = []

    async def publish_notification(self, notification) -> None:
        """Record an enqueued notification's ID."""
        self.published.append(notification.id)


def make_recipient(*, project_id: UUID, addresses: dict) -> Recipient:
    """Build a recipient for a project with the given channel addresses."""
    return Recipient(
        id=uuid4(),
        project_id=project_id,
        addresses=addresses,
    )


def make_template(*, project_id: UUID, channel=DeliveryChannel.EMAIL, body, subject):
    """Build a template for a project and channel."""
    return Template(
        id=uuid4(),
        project_id=project_id,
        name="welcome",
        slug="welcome",
        channel=channel,
        body=body,
        subject=subject,
    )


@pytest.fixture
def recipient():
    """Return a recipient with addresses on every channel."""
    return make_recipient(
        project_id=uuid4(),
        addresses={"email": "a@b.io", "sms": "+123", "push": "token"},
    )


@pytest.fixture
def service(recipient):
    """Return a NotificationService with intake collaborators pre-wired."""
    return NotificationService(
        idempotency_guard=FakeIdempotency(),
        repository=FakeRepository(),
        publisher=FakePublisher(),
        recipient_repository=FakeRecipientRepository({recipient.id: recipient}),
        template_resolver=NotificationTemplateResolver(FakeTemplateRepository()),
        policy_resolver=PolicyResolver(),
    )


def build_kwargs(
    recipient,
    *,
    subject: str | None = "Hi",
    body: str | None = "Hello world",
    key: str = "key-1",
    **overrides,
):
    """Assemble standard create_notification kwargs from a recipient.

    Email notifications require a subject, so both ``subject`` and ``body``
    are always present by default; pass ``subject=None`` to exercise the
    missing-subject path.
    """
    kwargs = dict(
        project_id=recipient.project_id,
        recipient_id=recipient.id,
        channel="email",
        subject=subject,
        body=body,
        idempotency_key=key,
        correlation_id=uuid4(),
    )
    kwargs.update(overrides)
    return kwargs


async def test_create_notification_persists_and_enqueues(service, recipient):
    """Create persists a pending email notification and enqueues it once."""
    notification = await service.create_notification(
        **build_kwargs(recipient, subject="Hi", body="Hello world")
    )

    assert notification.channel == DeliveryChannel.EMAIL
    assert notification.status == NotificationStatus.PENDING
    assert notification.content.subject == "Hi"
    assert notification.content.body == "Hello world"
    assert service._publisher.published == [notification.id]


async def test_duplicate_key_replays_original_without_requeue(service, recipient):
    """A duplicate idempotency key replays the original without a new enqueue."""
    kwargs = build_kwargs(recipient, subject="Hi", key="key-dup")

    first = await service.create_notification(**kwargs)
    second = await service.create_notification(**kwargs)

    assert second.id == first.id
    assert service._publisher.published == [first.id]

    listed = await service._repository.list_by_project(recipient.project_id, 10, 0)
    assert len(listed) == 1


async def test_email_without_subject_rejected(service, recipient):
    """An email notification without a subject is rejected."""
    with pytest.raises(Exception) as exc_info:
        await service.create_notification(**build_kwargs(recipient, subject=None))
    assert "subject" in str(exc_info.value).lower()


async def test_get_and_list_are_scoped_to_project(service, recipient):
    """Get raises not-found when the project does not own the notification."""
    from tiber.domain.exceptions import NotificationNotFoundError

    n_a = await service.create_notification(**build_kwargs(recipient, key="ka"))

    got = await service.get_notification(recipient.project_id, n_a.id)
    assert got.id == n_a.id

    with pytest.raises(NotificationNotFoundError):
        await service.get_notification(uuid4(), n_a.id)

    listed = await service._repository.list_by_project(recipient.project_id, 10, 0)
    assert listed == [n_a]


# ---------------------------------------------------------------------------
# Intake-time recipient scoping
# ---------------------------------------------------------------------------


async def test_missing_recipient_raises_not_found(recipient):
    """A notification for an unknown recipient is rejected."""
    svc = NotificationService(
        idempotency_guard=FakeIdempotency(),
        repository=FakeRepository(),
        publisher=FakePublisher(),
        recipient_repository=FakeRecipientRepository({}),
        template_resolver=NotificationTemplateResolver(FakeTemplateRepository()),
        policy_resolver=PolicyResolver(),
    )

    with pytest.raises(RecipientNotFoundError):
        await svc.create_notification(**build_kwargs(recipient))


async def test_recipient_from_other_project_rejected(recipient):
    """A recipient belonging to another project is a scope violation."""
    svc = NotificationService(
        idempotency_guard=FakeIdempotency(),
        repository=FakeRepository(),
        publisher=FakePublisher(),
        recipient_repository=FakeRecipientRepository({recipient.id: recipient}),
        template_resolver=NotificationTemplateResolver(FakeTemplateRepository()),
        policy_resolver=PolicyResolver(),
    )

    with pytest.raises(ProjectScopeViolationError):
        await svc.create_notification(
            **build_kwargs(recipient, key="recip", project_id=uuid4())
        )


# ---------------------------------------------------------------------------
# Intake-time template resolution & rendering
# ---------------------------------------------------------------------------


async def test_template_only_persists_rendered_snapshot(recipient):
    """A template-only POST (no body/subject) persists the rendered body."""
    template = make_template(
        project_id=recipient.project_id,
        body="Welcome {{name}}!",
        subject="Hi {{name}}",
    )
    svc = NotificationService(
        idempotency_guard=FakeIdempotency(),
        repository=FakeRepository(),
        publisher=FakePublisher(),
        recipient_repository=FakeRecipientRepository({recipient.id: recipient}),
        template_resolver=NotificationTemplateResolver(
            FakeTemplateRepository({template.id: template})
        ),
        policy_resolver=PolicyResolver(),
    )

    notification = await svc.create_notification(
        **build_kwargs(
            recipient,
            key="tpl-1",
            template_id=template.id,
            template_variables={"name": "Ada"},
        )
    )

    # The persisted snapshot is the rendered content, not a placeholder.
    assert notification.status == NotificationStatus.PENDING
    assert notification.content.body == "Welcome Ada!"
    assert notification.content.subject == "Hi Ada"
    assert "[template pending]" not in notification.content.body
    assert [notification.id] == svc._publisher.published


async def test_direct_content_without_body_rejected(service, recipient):
    """A direct-content notification (no template) requires a body."""
    with pytest.raises(ValueError):
        await service.create_notification(**build_kwargs(recipient, body=None))


async def test_cross_project_template_rejected():
    """A template owned by another project is rejected at intake."""
    recipient = make_recipient(project_id=uuid4(), addresses={"email": "a@b.io"})
    template = make_template(project_id=uuid4(), body="Hi", subject="Hi")
    svc = NotificationService(
        idempotency_guard=FakeIdempotency(),
        repository=FakeRepository(),
        publisher=FakePublisher(),
        recipient_repository=FakeRecipientRepository({recipient.id: recipient}),
        template_resolver=NotificationTemplateResolver(
            FakeTemplateRepository({template.id: template})
        ),
        policy_resolver=PolicyResolver(),
    )

    with pytest.raises(ProjectScopeViolationError):
        await svc.create_notification(
            **build_kwargs(recipient, key="tpl-xp", template_id=template.id)
        )


async def test_channel_mismatched_template_rejected():
    """A template for a different channel is rejected at intake."""
    recipient = make_recipient(
        project_id=uuid4(), addresses={"email": "a@b.io", "push": "tok"}
    )
    # Template targets push but the notification targets email.
    template = make_template(
        project_id=recipient.project_id,
        channel=DeliveryChannel.PUSH,
        body="Hi",
        subject=None,
    )
    svc = NotificationService(
        idempotency_guard=FakeIdempotency(),
        repository=FakeRepository(),
        publisher=FakePublisher(),
        recipient_repository=FakeRecipientRepository({recipient.id: recipient}),
        template_resolver=NotificationTemplateResolver(
            FakeTemplateRepository({template.id: template})
        ),
        policy_resolver=PolicyResolver(),
    )

    with pytest.raises(TemplateChannelMismatchError):
        await svc.create_notification(
            **build_kwargs(recipient, key="tpl-ch", template_id=template.id)
        )


# ---------------------------------------------------------------------------
# Intake-time policy resolution
# ---------------------------------------------------------------------------


async def test_policy_rejection_persists_and_does_not_publish(recipient):
    """A recipient lacking the channel address is persisted as policy_rejected."""
    # Recipient has no email address -> RecipientAddressRule rejects.
    no_email = make_recipient(
        project_id=recipient.project_id, addresses={"push": "token"}
    )
    svc = NotificationService(
        idempotency_guard=FakeIdempotency(),
        repository=FakeRepository(),
        publisher=FakePublisher(),
        recipient_repository=FakeRecipientRepository({no_email.id: no_email}),
        template_resolver=NotificationTemplateResolver(FakeTemplateRepository()),
        policy_resolver=PolicyResolver(),
    )

    notification = await svc.create_notification(**build_kwargs(no_email, key="pol-1"))

    assert notification.status == NotificationStatus.POLICY_REJECTED
    assert notification.policy_violation_reason is not None
    assert "email" in notification.policy_violation_reason
    # A rejected notification is a created record but is never enqueued.
    assert svc._publisher.published == []
