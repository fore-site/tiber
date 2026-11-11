"""Application service for creating notification topics."""

from uuid import UUID

from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import NotificationTopic
from tiber.domain.enums import NotificationCategory
from tiber.domain.exceptions import NameConflictError
from tiber.domain.repositories import NotificationTopicRepository


class NotificationTopicService:
    """Create notification topics within a project."""

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
