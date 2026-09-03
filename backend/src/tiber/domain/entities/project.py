from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID


@dataclass(frozen=True)
class Project:
    """Project entity."""

    id: UUID
    user_id: UUID
    name: str
    slug: str
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    archived_at: datetime | None = field(default=None)
