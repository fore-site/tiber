from typing import Protocol

from tiber.domain.entities import Notification


class MessagePublisher(Protocol):
    """Port for publishing notification jobs to asynchronous workers."""

    async def publish_notification(self, notification: Notification) -> None:
        """Enqueue the notification for asynchronous processing."""
        ...
