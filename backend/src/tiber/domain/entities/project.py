import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from ..exceptions import InvalidProjectStateError

_SLUG_RE: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SLUG_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")


def _derive_slug(name: str) -> str:
    """Derive a URL-safe slug from a project name.

    Lowercase ASCII letters and digits are kept as tokens and joined with
    single hyphens. All other characters are treated as token separators and discarded.
    """
    return "-".join(_SLUG_TOKEN_RE.findall(name.lower()))


def _require_derivable_name(name: str) -> None:
    """Raise unless the name can produce a non-empty slug."""
    if not _derive_slug(name):
        raise InvalidProjectStateError(
            "Project name must contain at least one ASCII letter or "
            f"digit for slug derivation (got: {name!r})"
        )


@dataclass(frozen=True, kw_only=True)
class Project:
    """Project entity."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
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
            raise InvalidProjectStateError("Project name must not be empty")

        if self.slug is None:
            _require_derivable_name(self.name)
            object.__setattr__(self, "slug", _derive_slug(self.name))

        if self.slug and not _SLUG_RE.fullmatch(self.slug):
            raise InvalidProjectStateError(
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
            raise InvalidProjectStateError("Project name must not be empty")
        _require_derivable_name(name)

        return replace(
            self,
            name=name,
            slug=_derive_slug(name),
            updated_at=datetime.now(UTC),
        )
