from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TemplateModel(Base):
    """Reusable notification content, one variant per delivery channel.

    ``variants`` maps a channel value to its content object (the same shape as
    ``NotificationContent.to_dict``). A template is always loaded and written
    as a whole, so the variants live in one JSONB column instead of a second
    table: there is no query that needs to address a single variant row.
    """

    __tablename__ = "templates"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "name",
            name="templates_name_unique",
        ),
        UniqueConstraint(
            "project_id",
            "template_slug",
            name="templates_project_slug_unique",
        ),
        CheckConstraint(
            "jsonb_typeof(variants) = 'object'",
            name="templates_variants_check",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    template_slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    variants: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
