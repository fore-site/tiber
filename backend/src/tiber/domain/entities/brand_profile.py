import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..exceptions import InvalidEntityAttributeError

_TOKEN_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_TOKEN_VALUE_RE = re.compile(r"^[#A-Za-z0-9 ,.%()+\-]+$")


@dataclass(frozen=True, kw_only=True)
class BrandProfile:
    """Project-scoped reusable visual design tokens."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    name: str
    tokens: dict[str, str]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate profile names and CSS-safe token values."""
        if not self.name or not self.name.strip():
            raise InvalidEntityAttributeError("Brand profile name must not be empty")
        if len(self.name) > 100:
            raise InvalidEntityAttributeError(
                "Brand profile name must be 100 characters or fewer"
            )
        if len(self.tokens) > 64:
            raise InvalidEntityAttributeError("A brand profile may contain 64 tokens")
        for key, value in self.tokens.items():
            if not _TOKEN_NAME_RE.fullmatch(key):
                raise InvalidEntityAttributeError(f"Invalid brand token name: {key!r}")
            if (
                not isinstance(value, str)
                or len(value) > 128
                or not _TOKEN_VALUE_RE.fullmatch(value)
                or "url" in value.lower()
                or "expression" in value.lower()
            ):
                raise InvalidEntityAttributeError(
                    f"Invalid CSS-safe value for brand token {key!r}"
                )

    @classmethod
    def create(
        cls, *, project_id: UUID, name: str, tokens: dict[str, str]
    ) -> BrandProfile:
        """Create a project-scoped brand profile."""
        return cls(project_id=project_id, name=name, tokens=tokens)

    def update(self, *, name: str, tokens: dict[str, str]) -> BrandProfile:
        """Return the updated profile with a fresh modification timestamp."""
        return replace(
            self,
            name=name,
            tokens=tokens,
            updated_at=datetime.now(UTC),
        )
