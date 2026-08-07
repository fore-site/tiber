from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..entities import Recipient


class RecipientRepository(Protocol):
    """Contract for recipient data access."""

    async def save(self, recipient: Recipient) -> Recipient:
        """Persist a recipient."""
        ...

    async def get_by_id(self, id: UUID) -> Recipient | None:
        """Get a recipient by its ID."""
        ...

    async def get_by_external_id(
        self, project_id: UUID, external_id: str
    ) -> Recipient | None:
        """Get a recipient for a project by its caller-supplied external ID."""
        ...

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Recipient]:
        """List recipients for a project with pagination."""
        ...
