import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

_SLUG_RE: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True, kw_only=True)
class Project:
    """Project entity.

    ``slug`` is the human-readable identifier clients choose at creation:
    URL-safe by construction (lowercase letters, digits, hyphens, no
    leading/trailing hyphen, no double hyphens) so it can appear in
    dashboard URLs and remain legible in logs. Immutable after creation.
    """

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    user_id: UUID
    name: str
    slug: str
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    archived_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        """Validate the project's state after initialization."""
        if not _SLUG_RE.fullmatch(self.slug):
            raise ValueError(
                "Project slug must be lowercase letters and digits separated "
                "by single hyphens, with no leading or trailing hyphen "
                f"(got: {self.slug!r})"
            )

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
