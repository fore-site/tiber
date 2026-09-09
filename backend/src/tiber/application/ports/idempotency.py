from typing import Protocol
from uuid import UUID


class IdempotencyGuard(Protocol):
    """Port for checking idempotent requests."""

    async def check_and_store(
        self, project_id: UUID, key: str, notification_id: UUID
    ) -> bool:
        """Return True if the key was not already stored (meaning the request can proceed)."""
        ...

    async def get_existing_notification_id(
        self, project_id: UUID, key: str
    ) -> UUID | None:
        """Return the ID of a previously stored notification for this key, if any."""
        ...
