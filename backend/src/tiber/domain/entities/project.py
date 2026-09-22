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
    single hyphens; everything else — spaces, punctuation, non-ASCII — acts
    as a separator. Returns "" when the name contains no ASCII alnum token
    at all, which the caller treats as an invalid name.
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
    """Project entity.

    ``slug`` is the normalized form of the current name: derived on every
    construction path (including direct instantiation) and re-derived on
    rename. Clients never author it. Per-user slug uniqueness is what
    enforces project name uniqueness, because derivation collapses name
    variants ("My App" and "my.app" normalize to the same slug).

    ``slug`` is ``None`` only as a *construction input* meaning "derive
    from name". After ``__post_init__`` it is always a format-valid str;
    reconstitute() supplies the stored slug so rehydration reproduces the
    row exactly instead of re-deriving.
    """

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    user_id: UUID
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
        cls, *, user_id: UUID, name: str, description: str | None = None
    ) -> Project:
        """Create a new project; the slug is derived from the name."""
        return cls(user_id=user_id, name=name, description=description)

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
        updated_at: datetime,
        archived_at: datetime | None,
    ) -> Project:
        """Rebuild an existing project from persisted state.

        The stored slug is required and loaded as-is: rehydration must
        reproduce the row exactly, never re-derive an identity.
        """
        return cls(
            id=id,
            user_id=user_id,
            name=name,
            slug=slug,
            description=description,
            created_at=created_at,
            updated_at=updated_at,
            archived_at=archived_at,
        )

    def rename(self, name: str) -> Project:
        """Rename the project; the slug follows the name.

        Bumps ``updated_at``: a rename is a mutation of the aggregate, and
        the entity-level stamp is the domain's own record that it happened
        (the persistence layer's ``onupdate`` only fires when a row is
        actually written, which is a different fact).
        """
        if not name or not name.strip():
            raise InvalidProjectStateError("Project name must not be empty")
        _require_derivable_name(name)

        return replace(
            self,
            name=name,
            slug=_derive_slug(name),
            updated_at=datetime.now(UTC),
        )
