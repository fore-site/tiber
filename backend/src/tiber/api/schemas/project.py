from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreateRequest(BaseModel):
    """Fields accepted when creating a project."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class ProjectUpdateRequest(ProjectCreateRequest):
    """Replacement fields accepted when updating a project."""


class ProjectResponse(BaseModel):
    """API representation of a project."""

    model_config = ConfigDict(
        from_attributes=True,
        frozen=True,
    )

    id: UUID

    name: str = Field(
        examples=["My Application"],
    )

    slug: str = Field(
        examples=["my-application"],
        description="Derived from the project name and regenerated on rename.",
    )

    description: str | None = None

    deleted: bool = Field(
        description=(
            "Indicates whether the project is deleted. "
            "deleted projects remain accessible for historical data "
            "but cannot accept new notifications or other mutating operations."
        ),
    )

    created_at: datetime

    updated_at: datetime

    deleted_at: datetime | None = None
