from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreateRequest(BaseModel):
    """Fields accepted when creating a project."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class ProjectUpdateRequest(BaseModel):
    """Optional fields accepted when updating a project.

    Omitting a field leaves it unchanged; sending `description: null` clears it.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def name_is_not_null(cls, name: str | None) -> str | None:
        """Reject an explicit null name; omission is the way to keep it."""
        if name is None:
            raise ValueError("name cannot be null; omit it to keep the current name")
        return name


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


class ProjectListResponse(BaseModel):
    """One cursor page of the authenticated account's projects."""

    data: list[ProjectResponse]
    next_cursor: str | None = None
