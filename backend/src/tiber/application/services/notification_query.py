"""Read side of notifications.

Replaces the read methods of the old ``NotificationService``, so read requests
no longer construct a publisher, an idempotency guard and a policy resolver they
never use. Once this is wired, the old ``NotificationService`` can be deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tiber.domain.entities import Notification, Recipient
from tiber.domain.entities.notification_intake import NotificationIntake
from tiber.domain.exceptions import EntityNotFoundError
from tiber.domain.repositories import (
    NotificationIntakeRepository,
    NotificationRepository,
    RecipientRepository,
)


@dataclass(frozen=True)
class NotificationRequestView:
    """An accepted request and what it produced so far."""

    intake: NotificationIntake
    notifications: list[Notification]  # empty until processing completes
    recipient: Recipient


class NotificationQueryService:
    """Read-only notification and request-status lookups."""

    def __init__(
        self,
        *,
        notification_repository: NotificationRepository,
        intake_repository: NotificationIntakeRepository,
        recipient_repository: RecipientRepository,
    ) -> None:
        """Initialize the read-side repositories."""
        self._notifications = notification_repository
        self._intakes = intake_repository
        self._recipients = recipient_repository

    async def get_notification(
        self, project_id: UUID, notification_id: UUID
    ) -> Notification:
        """Return one notification, scoped to the project."""
        notification = await self._notifications.get_by_id(notification_id, project_id)
        if notification is None or notification.project_id != project_id:
            raise EntityNotFoundError(Notification, str(notification_id))
        return notification

    async def list_notifications(
        self, project_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        """List a project's notifications with pagination."""
        return await self._notifications.list_by_project(project_id, limit, offset)

    async def get_request_status(
        self, project_id: UUID, correlation_id: UUID
    ) -> NotificationRequestView:
        """Status of one accepted request, scoped to the project."""
        intake = await self._intakes.get_by_correlation_id(correlation_id, project_id)
        if intake is None:
            raise EntityNotFoundError(NotificationIntake, str(correlation_id))

        recipient = await self._recipients.get_by_id(intake.recipient_id, project_id)
        if recipient is None:
            raise EntityNotFoundError(Recipient, str(intake.recipient_id))

        notifications = await self._notifications.list_by_correlation_id(
            correlation_id, project_id
        )
        return NotificationRequestView(intake, notifications, recipient)
