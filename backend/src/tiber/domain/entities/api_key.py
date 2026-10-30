from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class APIKey:
    """API Key entity - Auth tokens for client applications submitting notifications.

    ``expires_at`` is the instant from which the key stops working (``None`` means
    it never expires). ``revoked_at`` is set once, when the key is revoked.
    Both timestamps must be timezone-aware.
    """

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    name: str
    key_hash: str
    key_prefix: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = None
    expires_at: datetime | None = None

    @classmethod
    def create(
        cls, *, project_id: UUID, name: str, key_hash: str, key_prefix: str
    ) -> APIKey:
        """Create a new API key with a system-generated id and timestamps."""
        return cls(
            project_id=project_id, name=name, key_hash=key_hash, key_prefix=key_prefix
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        name: str,
        key_hash: str,
        key_prefix: str,
        created_at: datetime,
        revoked_at: datetime | None,
        expires_at: datetime | None,
    ) -> APIKey:
        """Rebuild an existing API key from persisted state."""
        return cls(
            id=id,
            project_id=project_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            created_at=created_at,
            revoked_at=revoked_at,
            expires_at=expires_at,
        )

    def is_revoked(self) -> bool:
        """Check if the key has been revoked. Revocation is permanent."""
        return self.revoked_at is not None

    def is_expired(self, now: datetime) -> bool:
        """Check if ``now`` has reached ``expired_at``."""
        return self.expires_at is not None and now >= self.expires_at

    def is_active(self, now: datetime) -> bool:
        """Check if the key may authenticate a request at ``now``."""
        return not self.is_revoked() and not self.is_expired(now)
