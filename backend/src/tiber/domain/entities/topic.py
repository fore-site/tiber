from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import NotificationCategory
from ..value_objects import TopicTitle


@dataclass(frozen=True, kw_only=True)
class NotificationTopic:
    """Entity for Notification category topics."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    category: NotificationCategory
    title: TopicTitle
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls, *, project_id: UUID, category: NotificationCategory, title: TopicTitle
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
        title: TopicTitle,
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

    def update(
        self,
        **changes,
    ) -> NotificationTopic:
        """Update an existing notification topic with new state."""
        return replace(
            self,
            **changes,
            updated_at=datetime.now(UTC),
        )
