"""Tests for transactional notification cancellation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tiber.application.services.notification_cancellation import (
    NotificationCancellationService,
)
from tiber.domain.entities import Notification
from tiber.domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    NotificationStatus,
    SendTimeBasis,
)
from tiber.domain.exceptions import EntityNotFoundError, InvalidStateTransitionError
from tiber.domain.value_objects import NotificationContent


class FakeUnitOfWork:
    """Track whether cancellation owns a unit-of-work boundary."""

    def __init__(self) -> None:
        """Initialize transaction counters."""
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> FakeUnitOfWork:
        """Enter one transaction."""
        self.entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit one transaction without suppressing errors."""
        self.exited += 1


class FakeNotificationRepository:
    """In-memory repository with the atomic pending-only cancellation contract."""

    def __init__(
        self,
        notification: Notification | None,
        *,
        change_before_cancel: NotificationStatus | None = None,
    ) -> None:
        """Store an optional notification and a simulated concurrent transition."""
        self.notification = notification
        self.change_before_cancel = change_before_cancel
        self.saved: Notification | None = None

    async def get_by_id(self, notification_id, project_id) -> Notification | None:
        """Return the notification only in its project scope."""
        notification = self.notification
        if (
            notification is None
            or notification.id != notification_id
            or notification.project_id != project_id
        ):
            return None
        return notification

    async def cancel_pending(self, notification: Notification) -> bool:
        """Persist cancellation only if the stored row remains pending."""
        if self.change_before_cancel is not None:
            assert self.notification is not None
            self.notification = _notification(
                status=self.change_before_cancel,
                project_id=self.notification.project_id,
                notification_id=self.notification.id,
            )
            return False
        if (
            self.notification is None
            or self.notification.status is not NotificationStatus.PENDING
        ):
            return False
        self.saved = notification
        self.notification = notification
        return True


def _notification(
    *,
    status: NotificationStatus = NotificationStatus.PENDING,
    project_id=None,
    notification_id=None,
) -> Notification:
    """Build an explicit, future-scheduled notification."""
    return Notification(
        id=notification_id or uuid4(),
        project_id=project_id or uuid4(),
        recipient_id=uuid4(),
        transaction_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.INFORMATIONAL,
        content=NotificationContent(title="Scheduled", plain_text_body="A message"),
        send_time_basis=SendTimeBasis.EXPLICIT,
        send_at=datetime.now(UTC) + timedelta(hours=1),
        status=status,
        cancellation_reason=(
            "cancelled by client" if status is NotificationStatus.CANCELLED else None
        ),
    )


@pytest.mark.asyncio
async def test_cancel_pending_notification_persists_domain_transition() -> None:
    """A pending scheduled notification transitions to cancelled in one UOW."""
    notification = _notification()
    uow = FakeUnitOfWork()
    repository = FakeNotificationRepository(notification)
    service = NotificationCancellationService(
        unit_of_work=uow,
        notification_repository=repository,
    )

    await service.cancel(notification.project_id, notification.id)

    assert repository.saved is not None
    assert repository.saved.status is NotificationStatus.CANCELLED
    assert repository.saved.cancellation_reason is None
    assert uow.entered == uow.exited == 1


@pytest.mark.asyncio
async def test_cancel_missing_or_out_of_scope_notification_is_not_found() -> None:
    """A project-scoped miss is reported without writing."""
    notification = _notification()
    uow = FakeUnitOfWork()
    repository = FakeNotificationRepository(notification)
    service = NotificationCancellationService(
        unit_of_work=uow,
        notification_repository=repository,
    )

    with pytest.raises(EntityNotFoundError):
        await service.cancel(uuid4(), notification.id)

    assert repository.saved is None
    assert uow.entered == uow.exited == 1


@pytest.mark.asyncio
async def test_cancel_non_pending_notification_is_a_conflict() -> None:
    """A notification already processing cannot be cancelled."""
    notification = _notification(status=NotificationStatus.PROCESSING)
    uow = FakeUnitOfWork()
    repository = FakeNotificationRepository(notification)
    service = NotificationCancellationService(
        unit_of_work=uow,
        notification_repository=repository,
    )

    with pytest.raises(InvalidStateTransitionError):
        await service.cancel(notification.project_id, notification.id)

    assert repository.saved is None


@pytest.mark.asyncio
async def test_cancel_does_not_overwrite_concurrent_processing_transition() -> None:
    """A state change after the initial read wins over stale cancellation data."""
    notification = _notification()
    uow = FakeUnitOfWork()
    repository = FakeNotificationRepository(
        notification,
        change_before_cancel=NotificationStatus.PROCESSING,
    )
    service = NotificationCancellationService(
        unit_of_work=uow,
        notification_repository=repository,
    )

    with pytest.raises(InvalidStateTransitionError):
        await service.cancel(notification.project_id, notification.id)

    assert repository.saved is None
    assert repository.notification is not None
    assert repository.notification.status is NotificationStatus.PROCESSING
    assert uow.entered == uow.exited == 1
