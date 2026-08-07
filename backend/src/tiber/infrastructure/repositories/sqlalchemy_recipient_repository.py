from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Recipient
from ...domain.repositories.recipient_repository import RecipientRepository
from ...infrastructure.models.recipient import RecipientModel


class SQLAlchemyRecipientRepository(RecipientRepository):
    """SQLAlchemy implementation of the RecipientRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, recipient: Recipient) -> Recipient:
        """Persist a recipient."""
        model = self._to_model(recipient)
        self._session.add(model)
        await self._session.flush()
        return recipient

    async def get_by_id(self, id: UUID) -> Recipient | None:
        """Get a recipient by its ID."""
        model = await self._session.get(RecipientModel, id)
        return self._to_entity(model) if model else None

    async def get_by_external_id(
        self, project_id: UUID, external_id: str
    ) -> Recipient | None:
        """Get a recipient for a project by its caller-supplied external ID."""
        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            .where(RecipientModel.external_id == external_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Recipient]:
        """List recipients for a project with pagination."""
        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            .limit(limit)
            .offset(offset)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _to_model(entity: Recipient) -> RecipientModel:
        return RecipientModel(
            id=entity.id,
            project_id=entity.project_id,
            external_id=entity.external_id,
            addresses=entity.addresses,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            archived_at=entity.archived_at,
        )

    @staticmethod
    def _to_entity(model: RecipientModel) -> Recipient:
        return Recipient(
            id=model.id,
            project_id=model.project_id,
            external_id=model.external_id,
            addresses=model.addresses,
            created_at=model.created_at,
            updated_at=model.updated_at,
            archived_at=model.archived_at,
        )
