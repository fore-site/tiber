from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..exceptions import InvalidEntityAttributeError
from ..services.slug import SLUG_RE, derive_slug, require_derivable_name


@dataclass(frozen=True, kw_only=True)
class Project:
    """Project entity."""

    id: UUID = field(default_factory=uuid4)
    account_id: UUID
    name: str
    slug: str | None = None
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    archived_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        """Validate state; derive the slug when the caller did not supply one."""
        if not self.name or not self.name.strip():
            raise InvalidEntityAttributeError("Project name must not be empty")

        if self.slug is None:
            require_derivable_name(self.name)
            object.__setattr__(self, "slug", derive_slug(self.name))

        if self.slug and not SLUG_RE.fullmatch(self.slug):
            raise InvalidEntityAttributeError(
                "Project slug must be lowercase letters and digits separated "
                "by single hyphens, with no leading or trailing hyphen "
                f"(got: {self.slug!r})"
            )

    @classmethod
    def create(
        cls, *, account_id: UUID, name: str, description: str | None = None
    ) -> Project:
        """Create a new project; the slug is derived from the name."""
        return cls(account_id=account_id, name=name, description=description)

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        account_id: UUID,
        name: str,
        slug: str,
        description: str | None,
        created_at: datetime,
        updated_at: datetime,
        archived_at: datetime | None,
    ) -> Project:
        """Rebuild an existing project from persisted state.

        The stored slug is required and loaded as-is: rehydration must
        reproduce the row exactly, never re-derive an identity.
        """
        return cls(
            id=id,
            account_id=account_id,
            name=name,
            slug=slug,
            description=description,
            created_at=created_at,
            updated_at=updated_at,
            archived_at=archived_at,
        )

    def rename(self, name: str) -> Project:
        """Rename the project; the slug follows the name."""
        if not name or not name.strip():
            raise InvalidEntityAttributeError("Project name must not be empty")
        require_derivable_name(name)

        return replace(
            self,
            name=name,
            slug=derive_slug(name),
            updated_at=datetime.now(UTC),
        )
