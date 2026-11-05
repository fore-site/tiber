from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import APIKey
from ...domain.repositories import APIKeyRepository
from ..models.api_key import APIKeyModel
from ..models.project import ProjectModel


class SQLAlchemyAPIKeyRepository(APIKeyRepository):
    """Persist API-key metadata and map it to the domain entity."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to one database session."""
        self._session = session

    async def save(self, api_key: APIKey) -> APIKey:
        """Insert or update an API key and flush its generated values."""
        model = await self._session.get(APIKeyModel, api_key.id)
        if model is None:
            model = APIKeyModel(id=api_key.id)
            self._session.add(model)

        model.project_id = api_key.project_id
        model.name = api_key.name
        model.key_hash = api_key.key_hash
        model.key_prefix = api_key.key_prefix
        model.created_at = api_key.created_at
        model.revoked_at = api_key.revoked_at
        model.expires_at = api_key.expires_at
        await self._session.flush()
        return api_key

    async def get_by_id(self, id: UUID, project_id: UUID) -> APIKey | None:
        """Load a key only when it belongs to the requested project."""
        model = await self._session.scalar(
            select(APIKeyModel).where(
                APIKeyModel.id == id,
                APIKeyModel.project_id == project_id,
            )
        )
        return self._to_entity(model) if model else None

    async def get_by_hash(self, key_hash: str) -> APIKey | None:
        """Load a key by its one-way credential hash."""
        model = await self._session.scalar(
            select(APIKeyModel).where(APIKeyModel.key_hash == key_hash)
        )
        return self._to_entity(model) if model else None

    async def revoke(self, id: UUID, project_id: UUID) -> None:
        """Mark an active project key revoked without changing its history."""
        model = await self._session.scalar(
            select(APIKeyModel).where(
                APIKeyModel.id == id,
                APIKeyModel.project_id == project_id,
            )
        )
        if model is not None and model.revoked_at is None:
            model.revoked_at = datetime.now(UTC)
            await self._session.flush()

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[APIKey]:
        """List a project's keys, newest first."""
        models = await self._session.scalars(
            select(APIKeyModel)
            .where(APIKeyModel.project_id == project_id)
            .order_by(APIKeyModel.created_at.desc(), APIKeyModel.id)
            .limit(limit)
            .offset(offset)
        )
        return [self._to_entity(model) for model in models]

    async def count_by_project(self, project_id: UUID) -> int:
        """Count all keys for a project."""
        count = await self._session.scalar(
            select(func.count())
            .select_from(APIKeyModel)
            .where(APIKeyModel.project_id == project_id)
        )
        return count or 0

    async def list_by_account(self, account_id: UUID) -> list[APIKey]:
        """List every API key belonging to a project owned by an account."""
        models = await self._session.scalars(
            select(APIKeyModel)
            .join(ProjectModel, APIKeyModel.project_id == ProjectModel.id)
            .where(ProjectModel.account_id == account_id)
            .order_by(APIKeyModel.project_id, APIKeyModel.created_at, APIKeyModel.id)
        )
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _to_entity(model: APIKeyModel) -> APIKey:
        return APIKey.reconstitute(
            id=model.id,
            project_id=model.project_id,
            name=model.name,
            key_hash=model.key_hash,
            key_prefix=model.key_prefix,
            created_at=model.created_at,
            revoked_at=model.revoked_at,
            expires_at=model.expires_at,
        )
