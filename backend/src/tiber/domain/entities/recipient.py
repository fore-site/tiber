from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Recipient:
    """Recipient entity - the intended destination of a notification.

    Mirrors the ``recipients`` table (docs/architecture/database/schema.sql).
    ``addresses`` is a non-empty mapping of channel -> channel-specific address
    (e.g. {"email": "a@b.io"}).
    """

    id: UUID
    project_id: UUID
    addresses: dict[str, Any]
    external_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the recipient's state after initialization."""
        if not self.addresses:
            raise ValueError("Recipient addresses must not be empty")
