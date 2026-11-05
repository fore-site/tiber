"""Persistence port for account authentication state."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..auth import AuthAccount


class AuthAccountRepository(Protocol):
    """Read and persist authentication state for platform accounts."""

    async def add(self, account: AuthAccount) -> AuthAccount:
        """Insert a new account."""
        ...

    async def save(self, account: AuthAccount) -> AuthAccount:
        """Persist changes to an existing account."""
        ...

    async def get_by_id(self, account_id: UUID) -> AuthAccount | None:
        """Find an account by ID."""
        ...

    async def get_by_email(self, email: str) -> AuthAccount | None:
        """Find an account by its case-insensitive email address."""
        ...

    async def get_by_email_or_pending_email(self, email: str) -> AuthAccount | None:
        """Find an account by its active or pending email address."""
        ...

    async def get_by_github_id(self, github_id: str) -> AuthAccount | None:
        """Find an account linked to a GitHub identity."""
        ...


class AccountIdentityConflictError(RuntimeError):
    """A unique account email or GitHub identity is already in use."""
