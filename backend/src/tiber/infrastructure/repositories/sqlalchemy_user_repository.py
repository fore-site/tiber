from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import User
from ...domain.enums import UserRole
from ...domain.repositories.user_repository import UserRepository
from ...infrastructure.models.user import UserModel


class SQLAlchemyUserRepository(UserRepository):
    """SQLAlchemy implementation of the UserRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, user: User) -> User:
        """Persist a user."""
        model = self._to_model(user)
        self._session.add(model)
        await self._session.flush()
        return user

    async def get_by_id(self, id: UUID) -> User | None:
        """Get a user by its ID."""
        model = await self._session.get(UserModel, id)
        return self._to_entity(model) if model else None

    async def get_by_email(self, email: str) -> User | None:
        """Get a user by its email address."""
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email.lower())
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    @staticmethod
    def _to_model(entity: User) -> UserModel:
        return UserModel(
            id=entity.id,
            email=entity.email,
            password_hash=entity.password_hash,
            role=entity.role,
            is_verified=entity.is_verified,
            pending_email=entity.pending_email,
            github_id=entity.github_id,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        return User(
            id=model.id,
            email=model.email,
            role=UserRole(model.role),
            password_hash=model.password_hash,
            is_verified=model.is_verified,
            pending_email=model.pending_email,
            github_id=model.github_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
