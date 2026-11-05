from typing import Protocol
from uuid import UUID

from tiber.domain.entities import Notification


class MessagePublisher(Protocol):
    """Port for publishing intake and notification jobs to asynchronous workers."""

    async def publish_intake(self, intake_id: UUID) -> None:
        """Enqueue one accepted intake for fan-out processing."""
        ...

    async def publish_notification(self, notification: Notification) -> None:
        """Enqueue the notification for asynchronous processing."""
        ...
