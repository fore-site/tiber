"""Unit tests for the NotificationService use case.

Pure-Python tests using in-memory fakes for the ports (idempotency guard,
repository, publisher) - no database or broker required.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from tiber.application.services import NotificationService
from tiber.domain.enums import DeliveryChannel, NotificationStatus


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


class FakePublisher:
    """In-memory MessagePublisher."""

    def __init__(self) -> None:
        """Initialize an empty published list."""
        self.published: list[UUID] = []

    async def publish_notification(self, notification_id: UUID) -> None:
        """Record an enqueued notification ID."""
        self.published.append(notification_id)


@pytest.fixture
def service():
    """Return a NotificationService wired to in-memory fakes."""
    return NotificationService(
        idempotency_guard=FakeIdempotency(),
        repository=FakeRepository(),
        publisher=FakePublisher(),
    )


async def test_create_notification_persists_and_enqueues(service):
    """Create persists a pending email notification and enqueues it once."""
    project_id, recipient_id = uuid4(), uuid4()
    notification = await service.create_notification(
        project_id=project_id,
        recipient_id=recipient_id,
        channel="email",
        subject="Hi",
        body="Hello world",
        idempotency_key="key-1",
        correlation_id=uuid4(),
    )

    assert notification.channel == DeliveryChannel.EMAIL
    assert notification.status == NotificationStatus.PENDING
    assert notification.content.subject == "Hi"
    assert notification.content.body == "Hello world"
    assert service._publisher.published == [notification.id]


async def test_duplicate_key_replays_original_without_requeue(service):
    """A duplicate idempotency key replays the original without a new enqueue."""
    project_id, recipient_id = uuid4(), uuid4()
    kwargs = dict(
        project_id=project_id,
        recipient_id=recipient_id,
        channel="email",
        subject="Hi",
        body="Hello world",
        idempotency_key="key-dup",
        correlation_id=uuid4(),
    )

    first = await service.create_notification(**kwargs)
    second = await service.create_notification(**kwargs)

    assert second.id == first.id
    assert service._publisher.published == [first.id]

    listed = await service._repository.list_by_project(project_id, 10, 0)
    assert len(listed) == 1


async def test_email_without_subject_rejected(service):
    """An email notification without a subject is rejected."""
    with pytest.raises(Exception) as exc_info:
        await service.create_notification(
            project_id=uuid4(),
            recipient_id=uuid4(),
            channel="email",
            body="Hello",
            idempotency_key="key-bad",
            correlation_id=uuid4(),
        )
    assert "subject" in str(exc_info.value).lower()


async def test_get_and_list_are_scoped_to_project(service):
    """Get raises not-found when the project does not own the notification."""
    from tiber.domain.exceptions import NotificationNotFoundError

    project_id_a, project_id_b = uuid4(), uuid4()
    n_a = await service.create_notification(
        project_id=project_id_a,
        recipient_id=uuid4(),
        channel="sms",
        body="A",
        idempotency_key="ka",
        correlation_id=uuid4(),
    )

    got = await service.get_notification(project_id_a, n_a.id)
    assert got.id == n_a.id

    with pytest.raises(NotificationNotFoundError):
        await service.get_notification(project_id_b, n_a.id)

    listed = await service._repository.list_by_project(project_id_a, 10, 0)
    assert listed == [n_a]
