from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class Project:
    """Project entity."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    user_id: UUID
    name: str
    slug: str
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    archived_at: datetime | None = field(default=None)

    @classmethod
    def create(
        cls, *, user_id: UUID, name: str, slug: str, description: str | None = None
    ) -> Project:
        """Create a new project with a system-generated id and timestamps."""
        return cls(user_id=user_id, name=name, slug=slug, description=description)

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        user_id: UUID,
        name: str,
        slug: str,
        description: str | None,
        created_at: datetime,
        archived_at: datetime | None,
    ) -> Project:
        """Rebuild an existing project from persisted state."""
        return cls(
            id=id,
            user_id=user_id,
            name=name,
            slug=slug,
            description=description,
            created_at=created_at,
            archived_at=archived_at,
        )
