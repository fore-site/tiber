from typing import Protocol

from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel, NotificationCategory


class ChannelSelection(Protocol):
    """The ML layer. Returns deliverable channel(s) for a notification."""

    async def select(
        self,
        *,
        recipient: Recipient,
        available: frozenset[DeliveryChannel],
        category: NotificationCategory,
    ) -> list[DeliveryChannel]:
        """Determine the appropriate channel(s) a notification should be sent through."""
        ...
