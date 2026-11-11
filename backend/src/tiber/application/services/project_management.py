"""Use cases for account-owned project lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import Project
from tiber.domain.exceptions import (
    EntityNotFoundError,
    ProjectScopeViolationError,
)
from tiber.domain.repositories import ProjectRepository

PROJECT_PURGE_GRACE_PERIOD = timedelta(days=90)


class ProjectManagementService:
    """Manage projects owned by one dashboard account."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        project_repository: ProjectRepository,
    ) -> None:
        """Bind project use cases to a transaction and repository."""
        self._uow = unit_of_work
        self._projects = project_repository

    async def create(
        self, *, account_id: UUID, name: str, description: str | None = None
    ) -> Project:
        """Create an explicitly requested project for an account."""
        project = Project.create(
            account_id=account_id,
            name=name,
            description=description,
        )
        async with self._uow:
            return await self._projects.save(project)

    async def list(self, *, account_id: UUID, limit: int, offset: int) -> list[Project]:
        """List all active and deleted projects owned by an account."""
        return await self._projects.list_by_account(account_id, limit, offset)

    async def get(self, *, account_id: UUID, project_id: UUID) -> Project:
        """Get a project while hiding projects owned by another account."""
        project = await self._projects.get_by_id(project_id)
        if project is None or project.account_id != account_id:
            raise EntityNotFoundError(Project, str(project_id))
        return project

    async def update(
        self,
        *,
        account_id: UUID,
        project_id: UUID,
        name: str,
        description: str | None,
    ) -> Project:
        """Replace an active project's name and description."""
        async with self._uow:
            project = await self._owned_project_for_update(account_id, project_id)
            if project.deleted:
                raise EntityNotFoundError(Project, str(project_id))
            return await self._projects.save(
                project.update(name=name, description=description)
            )

    async def delete(self, *, account_id: UUID, project_id: UUID) -> Project:
        """Delete a project and start its 90-day deletion grace period."""
        async with self._uow:
            project = await self._owned_project_for_update(account_id, project_id)
            return await self._projects.save(project.delete())

    async def restore(self, *, account_id: UUID, project_id: UUID) -> Project:
        """Restore an deleted project before its scheduled purge."""
        async with self._uow:
            project = await self._owned_project_for_update(account_id, project_id)
            return await self._projects.save(project.restore())

    async def purge_expired(self, *, limit: int = 100) -> int:
        """Permanently remove deleted projects after the grace period."""
        cutoff = datetime.now(UTC) - PROJECT_PURGE_GRACE_PERIOD
        async with self._uow:
            return await self._projects.purge_expired(cutoff, limit)

    async def _owned_project_for_update(
        self, account_id: UUID, project_id: UUID
    ) -> Project:
        project = await self._projects.get_by_id_for_update(project_id)
        if project is None:
            raise EntityNotFoundError(Project, str(project_id))
        if project.account_id != account_id:
            raise ProjectScopeViolationError(str(project_id), "Account does not own it")
        return project
