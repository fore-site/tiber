"""Read side of delivery attempts.

Attempts are written by the worker-side delivery processor; this service only
exposes them. Both reads are scoped through the notification, because a
delivery attempt carries no ``project_id`` of its own.

Pagination is keyset-based: the cursor is the last attempt number a client
saw, and the repository selects only greater numbers. Appending an attempt
between two page requests therefore cannot shift or duplicate a page.
"""

from __future__ import annotations

from uuid import UUID

from tiber.application.pagination import (
    CursorPage,
    decode_int_cursor,
    encode_cursor,
)
from tiber.domain.entities import DeliveryAttempt, Notification
from tiber.domain.exceptions import EntityNotFoundError
from tiber.domain.repositories import (
    DeliveryAttemptRepository,
    NotificationRepository,
)


class DeliveryAttemptQueryService:
    """Project-scoped reads of recorded delivery attempts."""

    def __init__(
        self,
        *,
        notification_repository: NotificationRepository,
        attempt_repository: DeliveryAttemptRepository,
    ) -> None:
        """Initialize the service with its read repositories."""
        self._notifications = notification_repository
        self._attempts = attempt_repository

    async def list(
        self,
        project_id: UUID,
        notification_id: UUID,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> CursorPage[DeliveryAttempt]:
        """List a page of a notification's attempts in attempt order."""
        await self._require_notification(project_id, notification_id)
        after = decode_int_cursor(cursor, field="attempt_number")
        attempts = await self._attempts.list_by_notification(
            notification_id, limit + 1, cursor=after
        )
        items = attempts[:limit]
        next_cursor = (
            encode_cursor(attempt_number=items[-1].attempt_number)
            if len(attempts) > limit
            else None
        )
        return CursorPage(items=items, next_cursor=next_cursor)

    async def get(
        self, project_id: UUID, notification_id: UUID, attempt_id: UUID
    ) -> DeliveryAttempt:
        """Return one attempt, scoped through its notification."""
        await self._require_notification(project_id, notification_id)
        attempt = await self._attempts.get_by_id(attempt_id, notification_id)
        if attempt is None:
            raise EntityNotFoundError(DeliveryAttempt, str(attempt_id))
        return attempt

    async def _require_notification(
        self, project_id: UUID, notification_id: UUID
    ) -> Notification:
        notification = await self._notifications.get_by_id(notification_id, project_id)
        if notification is None:
            raise EntityNotFoundError(Notification, str(notification_id))
        return notification
