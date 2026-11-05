from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Project
from ...domain.repositories import ProjectRepository
from ..models.project import ProjectModel


class SQLAlchemyProjectRepository(ProjectRepository):
    """SQLAlchemy implementation of project reads used by application services."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to one request-scoped session."""
        self._session = session

    async def save(self, project: Project) -> Project:
        """Persist project state without committing the transaction."""
        model = await self._session.get(ProjectModel, project.id)
        if model is None:
            model = ProjectModel(id=project.id)
            self._session.add(model)
        model.account_id = project.account_id
        model.name = project.name
        model.slug = project.slug
        model.description = project.description
        model.created_at = project.created_at
        model.updated_at = project.updated_at
        model.archived_at = project.archived_at
        await self._session.flush()
        return project

    async def get_by_id(self, id: UUID) -> Project | None:
        """Load a project by ID."""
        model = await self._session.get(ProjectModel, id)
        if model is None:
            return None
        return Project.reconstitute(
            id=model.id,
            account_id=model.account_id,
            name=model.name,
            slug=model.slug,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
            archived_at=model.archived_at,
        )

    async def get_by_slug(self, slug: str, account_id: UUID) -> Project | None:
        """Resolve a project slug within its account."""
        from sqlalchemy import select

        model = await self._session.scalar(
            select(ProjectModel).where(
                ProjectModel.slug == slug,
                ProjectModel.account_id == account_id,
            )
        )
        if model is None:
            return None
        return Project.reconstitute(
            id=model.id,
            account_id=model.account_id,
            name=model.name,
            slug=model.slug,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
            archived_at=model.archived_at,
        )
