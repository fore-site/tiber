from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import BrandProfile
from ...domain.exceptions import BrandProfileNameConflictError
from ...domain.repositories import BrandProfileRepository
from ..models.brand_profile import BrandProfileModel
from .sqlalchemy_errors import get_constraint_name

_BRAND_NAME_CONSTRAINT = "brand_profiles_project_name_unique"


class SQLAlchemyBrandProfileRepository(BrandProfileRepository):
    """SQLAlchemy implementation of project brand profile persistence."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to one request-scoped session."""
        self._session = session

    async def save(self, profile: BrandProfile) -> BrandProfile:
        """Insert or update a brand profile without committing."""
        try:
            async with self._session.begin_nested():
                model = await self._session.get(BrandProfileModel, profile.id)
                if model is None:
                    self._session.add(self._to_model(profile))
                else:
                    model.name = profile.name
                    model.tokens = profile.tokens
                    model.updated_at = profile.updated_at
                await self._session.flush()
        except IntegrityError as exc:
            if get_constraint_name(exc) == _BRAND_NAME_CONSTRAINT:
                raise BrandProfileNameConflictError from exc
            raise
        return profile

    async def get_by_id(self, id: UUID, project_id: UUID) -> BrandProfile | None:
        """Load a brand profile within its project's scope."""
        model = await self._session.get(BrandProfileModel, id)
        if model is None or model.project_id != project_id:
            return None
        return self._to_entity(model)

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[BrandProfile]:
        """List project brand profiles in a stable order."""
        result = await self._session.execute(
            select(BrandProfileModel)
            .where(BrandProfileModel.project_id == project_id)
            .order_by(BrandProfileModel.created_at.desc(), BrandProfileModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def delete(self, profile: BrandProfile) -> None:
        """Delete a profile and let template references become unstyled."""
        model = await self._session.get(BrandProfileModel, profile.id)
        if model is not None and model.project_id == profile.project_id:
            await self._session.delete(model)
            await self._session.flush()

    @staticmethod
    def _to_model(profile: BrandProfile) -> BrandProfileModel:
        return BrandProfileModel(
            id=profile.id,
            project_id=profile.project_id,
            name=profile.name,
            tokens=profile.tokens,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    @staticmethod
    def _to_entity(model: BrandProfileModel) -> BrandProfile:
        return BrandProfile(
            id=model.id,
            project_id=model.project_id,
            name=model.name,
            tokens=model.tokens,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
