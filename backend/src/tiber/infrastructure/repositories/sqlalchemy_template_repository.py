from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Template
from ...domain.enums import DeliveryChannel
from ...domain.repositories import TemplateRepository
from ...domain.value_objects import NotificationContent, TemplateVariant
from ...infrastructure.models.template import TemplateModel


class SQLAlchemyTemplateRepository(TemplateRepository):
    """SQLAlchemy implementation of the TemplateRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, template: Template) -> Template:
        """Persist a template, updating it in place when it already exists."""
        model = await self._session.get(TemplateModel, template.id)
        if model is None:
            self._session.add(self._to_model(template))
        else:
            model.name = template.name
            model.template_slug = template.template_slug
            model.variants = self._serialize_variants(template)
            model.updated_at = template.updated_at
        await self._session.flush()
        return template

    async def get_by_id(self, id: UUID, project_id: UUID) -> Template | None:
        """Get a template by its ID within a project's scope."""
        model = await self._session.get(TemplateModel, id)
        if model is not None and model.project_id != project_id:
            return None
        return self._to_entity(model) if model else None

    async def get_by_slug(self, slug: str, project_id: UUID) -> Template | None:
        """Get a template by its slug within a project's scope."""
        result = await self._session.execute(
            select(TemplateModel)
            .where(TemplateModel.project_id == project_id)
            .where(TemplateModel.template_slug == slug)
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
    def _serialize_variants(template: Template) -> dict:
        return {
            channel.value: variant.content.to_dict()
            for channel, variant in template.variants.items()
        }

    @classmethod
    def _to_model(cls, entity: Template) -> TemplateModel:
        return TemplateModel(
            id=entity.id,
            project_id=entity.project_id,
            name=entity.name,
            template_slug=entity.template_slug,
            variants=cls._serialize_variants(entity),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_entity(model: TemplateModel) -> Template:
        variants = [
            TemplateVariant(
                # JSONB keys round-trip as plain strings.
                channel=DeliveryChannel(channel),
                content=NotificationContent.from_dict(content),
            )
            for channel, content in model.variants.items()
        ]
        return Template.reconstitute(
            id=model.id,
            project_id=model.project_id,
            name=model.name,
            template_slug=model.template_slug,
            variants=variants,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
