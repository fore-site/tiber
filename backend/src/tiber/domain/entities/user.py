from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from ..enums import UserRole


@dataclass(frozen=True)
class User:
    """User entity - a platform account that owns projects.

    Mirrors the ``users`` table (docs/architecture/database/schema.sql). An
    account is identified by email and owns projects. OAuth (GitHub) accounts
    have a ``github_id`` and no ``password_hash``; email/password accounts
    have a ``password_hash``.
    """

    id: UUID
    email: str
    role: UserRole = UserRole.USER
    password_hash: str | None = None
    is_verified: bool = False
    pending_email: str | None = None
    github_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the user's state after initialization."""
        if not self.email or not self.email.strip():
            raise ValueError("User email must not be empty")
