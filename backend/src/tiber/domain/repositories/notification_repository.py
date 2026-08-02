from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..entities import Notification


class NotificationRepository(Protocol):
    """Contract for notification data access."""

    async def save(self, notification: Notification) -> Notification:
        """Persist a notification.

        Implementations are responsible for ensuring persistence semantics
        appropriate for their storage backend (e.g concurrency control).
        """
        ...

    async def get_by_id(self, id: UUID) -> Notification | None:
        """Get a notification by its ID."""
        ...

    async def get_by_idempotency_key(
        self, project_id: UUID, key: str
    ) -> Notification | None:
        """Get a notification by its idempotency key."""
        ...

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Notification]:
        """List all notifications for a project with pagination."""
        ...
