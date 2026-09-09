from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
        description="Immutable after creation.",
    )

    description: str | None = None

    archived: bool = Field(
        description=(
            "Indicates whether the project is archived. "
            "Archived projects remain accessible for historical data "
            "but cannot accept new notifications or other mutating operations."
        ),
    )

    created_at: datetime

    updated_at: datetime

    archived_at: datetime | None = None
