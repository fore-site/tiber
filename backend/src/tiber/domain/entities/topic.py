from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import NotificationCategory
from ..exceptions import InvalidEntityAttributeError
from ..services import set_enum_attribute
from ..services.slug import SLUG_RE, derive_slug, require_derivable_name


@dataclass(frozen=True, kw_only=True)
class NotificationTopic:
    """Entity for Notification category topics."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    category: NotificationCategory
    title: str
    topic_slug: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the topic's state after initialization."""
        set_enum_attribute(self, "category", NotificationCategory, self.category)

        if not self.title or not self.title.strip():
            raise InvalidEntityAttributeError("Topic title must not be empty")

        object.__setattr__(self, "value", self.title.lower().strip())

        if self.topic_slug is None:
            require_derivable_name(self.title)
            object.__setattr__(self, "template_slug", derive_slug(self.title))

        if self.topic_slug and not SLUG_RE.fullmatch(self.topic_slug):
            raise InvalidEntityAttributeError(
                "Topic slug must be lowercase letters and digits separated "
                "by single hyphens, with no leading or trailing hyphen "
                f"(got: {self.topic_slug!r})"
            )

    @classmethod
    def create(
        cls, *, project_id: UUID, category: NotificationCategory, title: str
    ) -> NotificationTopic:
        """Create a new notification topic with a system-generated id and timestamps."""
        return cls(project_id=project_id, category=category, title=title)

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        category: NotificationCategory,
        title: str,
        created_at: datetime,
        updated_at: datetime,
    ) -> NotificationTopic:
        """Rebuild an existing notification topic from persisted state."""
        return cls(
            id=id,
            project_id=project_id,
            category=category,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
        )

    def rename(self, title: str) -> NotificationTopic:
        """Rename the topic title; the slug follows the name."""
        if not title or not title.strip():
            raise InvalidEntityAttributeError("Slug title must not be empty")
        require_derivable_name(title)

        return replace(
            self,
            title=title,
            topic_slug=derive_slug(title),
            updated_at=datetime.now(UTC),
        )

    def update_category(self, category: NotificationCategory) -> NotificationTopic:
        """Change the category of a topic."""
        validated_category = NotificationCategory(category)
        return replace(self, category=validated_category, updated_at=datetime.now(UTC))
