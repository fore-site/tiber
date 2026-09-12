from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class APIKey:
    """API Key entity - Auth tokens for client applications submitting notifications."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    name: str
    key_hash: str
    key_prefix: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = None
    expired_at: datetime | None = None

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
        expired_at: datetime | None,
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
            expired_at=expired_at,
        )
