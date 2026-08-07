from typing import Protocol
from uuid import UUID

from ..entities import Project


class ProjectRepository(Protocol):
    """Contract for project data access."""

    async def save(self, project: Project) -> Project:
        """Save a project to the repository."""
        ...

    async def get_by_id(self, id: UUID) -> Project | None:
        """Get a project by its ID."""
        ...

    async def get_by_slug(self, slug: str) -> Project | None:
        """Get a project by its slug."""
        ...
