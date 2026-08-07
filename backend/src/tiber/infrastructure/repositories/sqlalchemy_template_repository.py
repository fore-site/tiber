from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Template
from ...domain.enums import DeliveryChannel
from ...domain.repositories.template_repository import TemplateRepository
from ...infrastructure.models.template import TemplateModel


class SQLAlchemyTemplateRepository(TemplateRepository):
    """SQLAlchemy implementation of the TemplateRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, template: Template) -> Template:
        """Persist a template."""
        model = self._to_model(template)
        self._session.add(model)
        await self._session.flush()
        return template

    async def get_by_id(self, id: UUID) -> Template | None:
        """Get a template by its ID."""
        model = await self._session.get(TemplateModel, id)
        return self._to_entity(model) if model else None

    async def get_by_slug(self, project_id: UUID, slug: str) -> Template | None:
        """Get a template for a project by its slug."""
        result = await self._session.execute(
            select(TemplateModel)
            .where(TemplateModel.project_id == project_id)
            .where(TemplateModel.slug == slug)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Template]:
        """List templates for a project with pagination."""
        result = await self._session.execute(
            select(TemplateModel)
            .where(TemplateModel.project_id == project_id)
            .limit(limit)
            .offset(offset)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _to_model(entity: Template) -> TemplateModel:
        return TemplateModel(
            id=entity.id,
            project_id=entity.project_id,
            name=entity.name,
            slug=entity.slug,
            channel=entity.channel,
            subject=entity.subject,
            body=entity.body,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_entity(model: TemplateModel) -> Template:
        return Template(
            id=model.id,
            project_id=model.project_id,
            name=model.name,
            slug=model.slug,
            channel=DeliveryChannel(model.channel),
            subject=model.subject,
            body=model.body,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
