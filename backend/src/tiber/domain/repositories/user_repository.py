from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..entities import User


class UserRepository(Protocol):
    """Contract for user data access."""

    async def save(self, user: User) -> User:
        """Persist a user."""
        ...

    async def get_by_id(self, id: UUID) -> User | None:
        """Get a user by its ID."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Get a user by its email address."""
        ...
