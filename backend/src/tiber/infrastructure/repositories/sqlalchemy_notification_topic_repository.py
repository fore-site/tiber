from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import NotificationTopic
from ...domain.enums import NotificationCategory
from ...domain.repositories import NotificationTopicRepository
from ...infrastructure.models.topic import NotificationTopicModel


class SQLAlchemyNotificationTopicRepository(NotificationTopicRepository):
    """SQLAlchemy implementation of the NotificationTopicRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, topic: NotificationTopic) -> NotificationTopic:
        """Persist a topic, updating it in place when it already exists."""
        model = await self._session.get(NotificationTopicModel, topic.id)
        if model is None:
            self._session.add(self._to_model(topic))
        else:
            model.category = topic.category
            model.title = topic.title
            model.topic_slug = topic.topic_slug
            model.updated_at = topic.updated_at
        await self._session.flush()
        return topic

    async def get_by_id(self, id: UUID, project_id: UUID) -> NotificationTopic | None:
        """Get a notification topic by its ID within a project's scope."""
        model = await self._session.get(NotificationTopicModel, id)
        if model is not None and model.project_id != project_id:
            return None
        return self._to_entity(model) if model else None

    async def get_by_slug(
        self, slug: str, project_id: UUID
    ) -> NotificationTopic | None:
        """Get a notification topic by its slug within a project's scope."""
        result = await self._session.execute(
            select(NotificationTopicModel)
            .where(NotificationTopicModel.project_id == project_id)
            .where(NotificationTopicModel.topic_slug == slug)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_title(
        self, title: str, project_id: UUID
    ) -> NotificationTopic | None:
        """Get a notification topic by its title within a project's scope."""
        result = await self._session.execute(
            select(NotificationTopicModel)
            .where(NotificationTopicModel.project_id == project_id)
            .where(NotificationTopicModel.title == title)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_category(
        self,
        project_id: UUID,
        category: NotificationCategory,
        limit: int,
        offset: int,
    ) -> list[NotificationTopic]:
        """List the topics of one category within a project."""
        result = await self._session.execute(
            select(NotificationTopicModel)
            .where(NotificationTopicModel.project_id == project_id)
            .where(NotificationTopicModel.category == category.value)
            .limit(limit)
            .offset(offset)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[NotificationTopic]:
        """List topics for a project with pagination."""
        result = await self._session.execute(
            select(NotificationTopicModel)
            .where(NotificationTopicModel.project_id == project_id)
            .limit(limit)
            .offset(offset)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_model(entity: NotificationTopic) -> NotificationTopicModel:
        return NotificationTopicModel(
            id=entity.id,
            project_id=entity.project_id,
            category=entity.category,
            title=entity.title,
            topic_slug=entity.topic_slug,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_entity(model: NotificationTopicModel) -> NotificationTopic:
        return NotificationTopic.reconstitute(
            id=model.id,
            project_id=model.project_id,
            # Enum columns load as plain strings; the domain compares members.
            category=NotificationCategory(model.category),
            title=model.title,
            topic_slug=model.topic_slug,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
