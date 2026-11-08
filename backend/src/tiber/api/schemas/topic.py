from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...domain.entities import NotificationTopic
from ...domain.enums import NotificationCategory


class NotificationTopicCreateRequest(BaseModel):
    """Fields accepted when creating a notification topic."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: str = Field(min_length=1, max_length=200)
    category: NotificationCategory


class NotificationTopicResponse(BaseModel):
    """API representation of a persisted notification topic."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    category: NotificationCategory
    title: str
    topic_slug: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, topic: NotificationTopic) -> NotificationTopicResponse:
        """Build the API representation from a domain topic."""
        return cls(
            id=topic.id,
            project_id=topic.project_id,
            category=topic.category,
            title=topic.title,
            topic_slug=topic.topic_slug,
            created_at=topic.created_at,
            updated_at=topic.updated_at,
        )
