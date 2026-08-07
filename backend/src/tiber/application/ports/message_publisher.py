from abc import ABC, abstractmethod

from tiber.domain.entities import Notification


class MessagePublisher(ABC):
    """Port for publishing notification jobs to asynchronous workers."""

    @abstractmethod
    async def publish_notification(self, notification: Notification) -> None:
        """Enqueue the notification for asynchronous processing."""
        ...
