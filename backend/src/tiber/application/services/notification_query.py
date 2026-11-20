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
from tiber.domain.enums import DeliveryChannel, NotificationStatus
from tiber.domain.exceptions import EntityNotFoundError
from tiber.domain.repositories import (
    NotificationIntakeRepository,
    NotificationRepository,
    RecipientRepository,
)

from ..pagination import CursorPage, decode_time_id_cursor, encode_cursor


@dataclass(frozen=True)
class NotificationRequestView:
    """An accepted request and what it produced so far."""

    intake: NotificationIntake
    notifications: list[Notification]  # empty until processing completes
    # None once the recipient is erased: the request still happened, so its
    # status stays readable instead of turning into a 404.
    recipient: Recipient | None


@dataclass(frozen=True)
class NotificationView:
    """One notification plus the client-facing identity of its recipient."""

    notification: Notification
    recipient: str | None


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

    async def get_notification_view(
        self, project_id: UUID, notification_id: UUID
    ) -> NotificationView:
        """Return one notification with its recipient's external identifier."""
        notification = await self.get_notification(project_id, notification_id)
        recipient = (
            await self._recipients.get_by_id(notification.recipient_id, project_id)
            if notification.recipient_id is not None
            else None
        )
        return NotificationView(
            notification=notification,
            recipient=recipient.external_id if recipient is not None else None,
        )

    async def list_notifications(
        self,
        project_id: UUID,
        limit: int = 50,
        *,
        cursor: str | None = None,
        recipient: str | None = None,
        channel: DeliveryChannel | None = None,
        status: NotificationStatus | None = None,
    ) -> CursorPage[NotificationView]:
        """List a page of a project's notifications, newest first."""
        recipient_id: UUID | None = None
        if recipient is not None:
            owner = await self._recipients.get_by_external_id(recipient, project_id)
            if owner is None:
                raise EntityNotFoundError(Recipient, recipient)
            recipient_id = owner.id

        after = decode_time_id_cursor(cursor, time_field="created_at")
        notifications = await self._notifications.list_by_project(
            project_id,
            limit + 1,
            cursor=after,
            recipient_id=recipient_id,
            channel=channel,
            status=status,
        )
        items = notifications[:limit]
        # Sorted, because a stable key set keeps the batch lookup deterministic;
        # erased recipients contribute no id, and ``None`` is not orderable
        # against a UUID, so they are dropped rather than mixed in.
        recipients = await self._recipients.get_many_by_ids(
            project_id,
            sorted({n.recipient_id for n in items if n.recipient_id is not None}),
        )
        external_ids = {r.id: r.external_id for r in recipients}
        next_cursor = (
            encode_cursor(
                created_at=items[-1].created_at.isoformat(),
                id=items[-1].id,
            )
            if len(notifications) > limit
            else None
        )
        return CursorPage(
            items=[
                NotificationView(
                    notification=n,
                    recipient=external_ids.get(n.recipient_id),
                )
                for n in items
            ],
            next_cursor=next_cursor,
        )

    async def get_request_status(
        self, project_id: UUID, transaction_id: UUID
    ) -> NotificationRequestView:
        """Status of one accepted request, scoped to the project.

        The recipient is reported when it can still be resolved. An erased
        recipient is not an error: the request was accepted and the
        notifications were sent, so the status answers with what it has.
        """
        intake = await self._intakes.get_by_transaction_id(transaction_id, project_id)
        if intake is None:
            raise EntityNotFoundError(NotificationIntake, str(transaction_id))

        recipient = (
            await self._recipients.get_by_id(intake.recipient_id, project_id)
            if intake.recipient_id is not None
            else None
        )

        notifications = await self._notifications.list_by_transaction_id(
            transaction_id, project_id
        )
        return NotificationRequestView(intake, notifications, recipient)
