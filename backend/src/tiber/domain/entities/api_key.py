from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID


@dataclass(frozen=True)
class APIKey:
    """API Key entity - Auth tokens for client applications submitting notifications."""

    id: UUID
    project_id: UUID
    name: str
    key_hash: str
    key_prefix: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = None
    expired_at: datetime | None = None
