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
    slug: str
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        """Validate state; derive the slug when the caller did not supply one."""
        if not self.name or not self.name.strip():
            raise InvalidEntityAttributeError("Project name must not be empty")
        if len(self.name) > 100:
            raise InvalidEntityAttributeError(
                "Project name must be 100 characters or fewer"
            )
        if self.description is not None and len(self.description) > 1000:
            raise InvalidEntityAttributeError(
                "Project description must be 1000 characters or fewer"
            )

    @classmethod
    def create(
        cls, *, account_id: UUID, name: str, description: str | None = None
    ) -> Project:
        """Create a new project; the slug is derived from the name."""
        require_derivable_name(name)
        return cls(
            account_id=account_id,
            name=name,
            slug=derive_slug(name),
            description=description,
        )

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
        deleted_at: datetime | None,
    ) -> Project:
        """Rebuild an existing project from persisted state.

        The stored slug is required and loaded as-is: rehydration must
        reproduce the row exactly, never re-derive an identity.
        """
        if not SLUG_RE.fullmatch(slug):
            raise InvalidEntityAttributeError(
                "Project slug must be lowercase letters and digits separated "
                "by single hyphens, with no leading or trailing hyphen "
                f"(got: {slug!r})"
            )
        return cls(
            id=id,
            account_id=account_id,
            name=name,
            slug=slug,
            description=description,
            created_at=created_at,
            updated_at=updated_at,
            deleted_at=deleted_at,
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

    @property
    def deleted(self) -> bool:
        """Whether the project is in its 90-day deletion grace period."""
        return self.deleted_at is not None

    def update(self, *, name: str, description: str | None) -> Project:
        """Replace the project's editable details."""
        renamed = self.rename(name)
        return replace(renamed, description=description)

    def delete(self) -> Project:
        """Make the project soft deleted and start its hard deletion grace period."""
        if self.deleted:
            return self
        now = datetime.now(UTC)
        return replace(self, deleted_at=now, updated_at=now)

    def restore(self) -> Project:
        """Restore a deleted project and cancel its scheduled deletion."""
        if not self.deleted:
            return self
        return replace(
            self,
            deleted_at=None,
            updated_at=datetime.now(UTC),
        )
