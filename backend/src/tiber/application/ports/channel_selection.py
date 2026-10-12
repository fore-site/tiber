from typing import Protocol

from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel, NotificationCategory


class ChannelSelection(Protocol):
    """The ML layer. Returns deliverable channel for a notification."""

    async def rank(
        self,
        *,
        recipient: Recipient,
        available: frozenset[DeliveryChannel],
        category: NotificationCategory,
    ) -> DeliveryChannel:
        """Determine the appropriate channel a notification should be sent through."""
        ...
