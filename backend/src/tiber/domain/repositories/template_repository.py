from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..entities import Template


class TemplateRepository(Protocol):
    """Contract for template data access."""

    async def save(self, template: Template) -> Template:
        """Persist a template."""
        ...

    async def get_by_id(self, id: UUID) -> Template | None:
        """Get a template by its ID."""
        ...

    async def get_by_slug(self, project_id: UUID, slug: str) -> Template | None:
        """Get a template for a project by its slug."""
        ...

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Template]:
        """List templates for a project with pagination."""
        ...
