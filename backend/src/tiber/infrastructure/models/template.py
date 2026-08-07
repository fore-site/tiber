from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .types import DeliveryChannel, DeliveryChannelType


class TemplateModel(Base):
    """Reusable notification content templates with {{variable}} interpolation."""

    __tablename__ = "templates"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "slug",
            name="templates_project_slug_unique",
        ),
        UniqueConstraint(
            "project_id",
            "name",
            name="templates_name_unique",
        ),
        CheckConstraint(
            "(channel = 'email' AND subject IS NOT NULL) "
            "OR (channel <> 'email' AND subject IS NULL)",
            name="templates_subject_check",
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

    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    channel: Mapped[DeliveryChannel] = mapped_column(
        DeliveryChannelType,
        nullable=False,
    )

    subject: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    body: Mapped[str] = mapped_column(
        Text,
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
