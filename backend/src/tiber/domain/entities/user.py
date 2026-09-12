from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import UserRole


@dataclass(frozen=True, kw_only=True)
class User:
    """User entity - a platform account that owns projects.

    An account is identified by email and owns projects. OAuth (GitHub) accounts
    have a ``github_id`` and no ``password_hash``; email/password accounts
    have a ``password_hash``.
    """

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
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

    @classmethod
    def create(
        cls,
        *,
        email: str,
        role: UserRole = UserRole.USER,
        password_hash: str | None = None,
        github_id: str | None = None,
    ) -> User:
        """Create a new user with a system-generated id and timestamps."""
        return cls(
            email=email,
            role=role,
            password_hash=password_hash,
            github_id=github_id,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        email: str,
        role: UserRole,
        password_hash: str | None,
        is_verified: bool,
        pending_email: str | None,
        github_id: str | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> User:
        """Rebuild an existing user from persisted state."""
        return cls(
            id=id,
            email=email,
            role=role,
            password_hash=password_hash,
            is_verified=is_verified,
            pending_email=pending_email,
            github_id=github_id,
            created_at=created_at,
            updated_at=updated_at,
        )
