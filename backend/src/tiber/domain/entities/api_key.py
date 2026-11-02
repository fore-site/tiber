from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..exceptions import InvalidEntityAttributeError


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

    def __post_init__(self) -> None:
        """Validate the API key's state after construction or reconstitution."""
        if not self.name.strip():
            raise InvalidEntityAttributeError("API key name must not be empty")

        for field_name in ("created_at", "revoked_at", "expires_at"):
            value = getattr(self, field_name)
            if value is not None:
                self._require_timezone_aware(value, field_name)

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        name: str,
        key_hash: str,
        key_prefix: str,
        expires_at: datetime | None = None,
    ) -> APIKey:
        """Create a new API key with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            expires_at=expires_at,
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
        """Check if ``now`` has reached ``expires_at``."""
        self._require_timezone_aware(now, "now")
        return self.expires_at is not None and now >= self.expires_at

    def is_active(self, now: datetime) -> bool:
        """Check if the key may authenticate a request at ``now``."""
        self._require_timezone_aware(now, "now")
        return not self.is_revoked() and not self.is_expired(now)

    def revoke(self, at: datetime | None = None) -> APIKey:
        """Return a revoked copy of this key.

        Revocation is permanent and idempotent: revoking an already-revoked key
        returns the existing entity unchanged. ``at`` is injectable so callers
        can use the domain operation with a persisted event time and tests can
        avoid depending on the wall clock.
        """
        if self.is_revoked():
            return self

        revoked_at = at or datetime.now(UTC)
        self._require_timezone_aware(revoked_at, "revoked_at")
        return replace(self, revoked_at=revoked_at)

    @staticmethod
    def _require_timezone_aware(value: datetime, field_name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidEntityAttributeError(f"`{field_name}` must be timezone-aware")
