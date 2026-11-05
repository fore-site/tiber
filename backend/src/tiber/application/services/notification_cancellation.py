"""Use case for cancelling notifications that have not started processing."""

from __future__ import annotations

from uuid import UUID

from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import Notification
from tiber.domain.enums import NotificationStatus
from tiber.domain.exceptions import EntityNotFoundError, InvalidStateTransitionError
from tiber.domain.repositories import NotificationRepository


class NotificationCancellationService:
    """Cancel a project-scoped notification within a transaction."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        notification_repository: NotificationRepository,
    ) -> None:
        """Bind the transaction boundary and notification repository."""
        self._uow = unit_of_work
        self._notifications = notification_repository

    async def cancel(self, project_id: UUID, notification_id: UUID) -> None:
        """Cancel a pending notification, rejecting missing or non-pending rows."""
        async with self._uow:
            notification = await self._notifications.get_by_id(
                notification_id,
                project_id,
            )
            if notification is None:
                raise EntityNotFoundError(Notification, str(notification_id))

            cancelled = notification.mark_cancelled()
            if await self._notifications.cancel_pending(cancelled):
                return

            current = await self._notifications.get_by_id(notification_id, project_id)
            if current is None:
                raise EntityNotFoundError(Notification, str(notification_id))
            raise InvalidStateTransitionError(
                current.status,
                NotificationStatus.CANCELLED,
            )
