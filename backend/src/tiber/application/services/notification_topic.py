"""Application service for notification topics."""

from uuid import UUID

from tiber.application.pagination import (
    CursorPage,
    decode_time_id_cursor,
    encode_cursor,
)
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import NotificationTopic
from tiber.domain.enums import NotificationCategory
from tiber.domain.exceptions import EntityNotFoundError, NameConflictError
from tiber.domain.repositories import NotificationTopicRepository


class NotificationTopicService:
    """Create and list notification topics within a project."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        topic_repository: NotificationTopicRepository,
    ) -> None:
        """Initialize the service with persistence dependencies."""
        self._uow = unit_of_work
        self._topics = topic_repository

    async def create(
        self,
        *,
        project_id: UUID,
        title: str,
        category: NotificationCategory,
    ) -> NotificationTopic:
        """Create and persist a topic with a project-unique derived slug."""
        topic = NotificationTopic.create(
            project_id=project_id,
            title=title,
            category=category,
        )
        async with self._uow:
            existing = await self._topics.get_by_slug(topic.topic_slug, project_id)
            if existing is not None:
                raise NameConflictError(NotificationTopic)
            return await self._topics.save(topic)

    async def get(self, project_id: UUID, topic_id: UUID) -> NotificationTopic:
        """Return one topic, scoped to its project."""
        topic = await self._topics.get_by_id(topic_id, project_id)
        if topic is None:
            raise EntityNotFoundError(NotificationTopic, str(topic_id))
        return topic

    async def update(
        self,
        *,
        project_id: UUID,
        topic_id: UUID,
        title: str | None,
        category: NotificationCategory | None,
    ) -> NotificationTopic:
        """Apply the supplied title and/or category changes."""
        topic = await self.get(project_id, topic_id)
        updated = topic
        if title is not None:
            updated = updated.rename(title)
        if category is not None:
            updated = updated.update_category(category)
        if updated == topic:
            return topic
        async with self._uow:
            return await self._topics.save(updated)

    async def delete(self, project_id: UUID, topic_id: UUID) -> None:
        """Permanently delete a topic; existing notifications become topic-less."""
        topic = await self.get(project_id, topic_id)
        async with self._uow:
            await self._topics.delete(topic)

    async def list(
        self, project_id: UUID, *, limit: int = 50, cursor: str | None = None
    ) -> CursorPage[NotificationTopic]:
        """List one page of a project's topics, newest first."""
        after = decode_time_id_cursor(cursor, time_field="created_at")
        topics = await self._topics.list_by_project(project_id, limit + 1, cursor=after)
        items = topics[:limit]
        next_cursor = (
            encode_cursor(
                created_at=items[-1].created_at.isoformat(),
                id=items[-1].id,
            )
            if len(topics) > limit
            else None
        )
        return CursorPage(items=items, next_cursor=next_cursor)
