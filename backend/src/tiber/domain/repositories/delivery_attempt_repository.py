from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..entities import DeliveryAttempt


class DeliveryAttemptRepository(Protocol):
    """Contract for delivery-attempt data access."""

    async def save(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        """Persist a delivery attempt."""
        ...

    async def list_by_notification(
        self, notification_id: UUID
    ) -> list[DeliveryAttempt]:
        """List all attempts for a notification, oldest first."""
        ...
