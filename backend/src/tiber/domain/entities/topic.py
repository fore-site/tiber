from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import NotificationCategory
from ..value_objects import TopicSlug


@dataclass(frozen=True, kw_only=True)
class NotificationTopic:
    """Entity for Notification category topics."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    category: NotificationCategory
    slug: TopicSlug
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
