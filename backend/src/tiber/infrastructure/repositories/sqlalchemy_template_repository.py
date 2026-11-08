from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Template
from ...domain.enums import DeliveryChannel
from ...domain.exceptions import TemplateNameConflictError
from ...domain.repositories import TemplateRepository
from ...domain.value_objects import (
    ContentAction,
    ContentImage,
    NotificationContent,
    TemplateVariant,
)
from ...infrastructure.models.template import TemplateModel, TemplateVariantModel
from .sqlalchemy_errors import get_constraint_name

_TEMPLATE_NAME_CONSTRAINT = "templates_project_slug_unique"


class SQLAlchemyTemplateRepository(TemplateRepository):
    """SQLAlchemy implementation of the TemplateRepository.

    Never commits or rolls back: the unit of work owns the transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, template: Template) -> Template:
        """Insert a template, or update the row with the same ID.

        Templates are immutable entities: ``add_or_update_variants``,
        ``remove_variant`` and ``rename`` return a new entity with the same id, so
        persistence must update rather than re-insert. ``merge`` also removes the
        variants the new entity no longer has (delete-orphan).
        """
        try:
            async with self._session.begin_nested():
                await self._session.merge(self._to_model(template))
                await self._session.flush()
        except IntegrityError as exc:
            if get_constraint_name(exc) == _TEMPLATE_NAME_CONSTRAINT:
                raise TemplateNameConflictError from exc
            raise
        return template

    async def get_by_id(self, id: UUID, project_id: UUID) -> Template | None:
        """Get a template by its ID within a project's scope."""
        model = await self._session.get(TemplateModel, id)
        if model is None or model.project_id != project_id:
            return None
        return self._to_entity(model)

    async def get_by_slug(self, slug: str, project_id: UUID) -> Template | None:
        """Get a template by the slug clients send, within a project's scope."""
        result = await self._session.execute(
            select(TemplateModel)
            .where(TemplateModel.project_id == project_id)
            .where(TemplateModel.template_slug == slug)
        )
        model = result.scalars().first()  # unique per (project_id, template_slug)
        return self._to_entity(model) if model else None

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        offset: int,
        channel: DeliveryChannel | None = None,
    ) -> list[Template]:
        """List a project's templates, newest first, with pagination."""
        statement = select(TemplateModel).where(TemplateModel.project_id == project_id)
        if channel is not None:
            statement = statement.join(TemplateVariantModel).where(
                TemplateVariantModel.channel == channel.value
            )
        result = await self._session.execute(
            statement
            # Offset pagination needs a total order, or pages can repeat or skip rows.
            .order_by(TemplateModel.created_at.desc(), TemplateModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def delete(self, template: Template) -> None:
        """Delete a template without committing its transaction."""
        model = await self._session.get(TemplateModel, template.id)
        if model is not None and model.project_id == template.project_id:
            await self._session.delete(model)
            await self._session.flush()

    @staticmethod
    def _to_model(entity: Template) -> TemplateModel:
        # ``actions`` and ``images`` are NOT NULL JSONB and always carry a list
        # (asyncpg would write an explicit Python None as JSON null, not SQL NULL).
        # The channel is stored as its plain string value so the composite primary
        # key matches the identity of rows loaded from the database.
        return TemplateModel(
            id=entity.id,
            project_id=entity.project_id,
            brand_profile_id=entity.brand_profile_id,
            name=entity.name,
            template_slug=entity.template_slug,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            variants=[
                TemplateVariantModel(
                    template_id=entity.id,
                    channel=channel.value,
                    title=variant.content.title,
                    body=variant.content.plain_text_body,
                    html_body=variant.content.html_body,
                    actions=[
                        {"label": a.label, "url": a.url}
                        for a in variant.content.actions
                    ],
                    images=[
                        {"url": i.url, "alt": i.alt} for i in variant.content.images
                    ],
                )
                for channel, variant in entity.variants.items()
            ],
        )

    @staticmethod
    def _to_entity(model: TemplateModel) -> Template:
        return Template.reconstitute(
            id=model.id,
            project_id=model.project_id,
            name=model.name,
            brand_profile_id=model.brand_profile_id,
            variants=[
                TemplateVariant(
                    channel=DeliveryChannel(v.channel),
                    content=NotificationContent(
                        title=v.title,
                        plain_text_body=v.body,
                        html_body=v.html_body,
                        actions=tuple(
                            ContentAction(label=a["label"], url=a["url"])
                            for a in (v.actions or [])
                        ),
                        images=tuple(
                            ContentImage(url=i["url"], alt=i.get("alt"))
                            for i in (v.images or [])
                        ),
                    ),
                )
                for v in model.variants
            ],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
