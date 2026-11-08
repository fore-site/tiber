from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .types import DeliveryChannel, DeliveryChannelType


class TemplateModel(Base):
    """A template: one row per template, one variant row per channel."""

    __tablename__ = "templates"

    __table_args__ = (
        # Clients address templates by slug, so it is unique per project.
        UniqueConstraint(
            "project_id",
            "template_slug",
            name="templates_project_slug_unique",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    )

    brand_profile_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "brand_profiles.id",
            ondelete="SET NULL",
            name="templates_brand_profile_id_fkey",
        ),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)

    template_slug: Mapped[str] = mapped_column(Text, nullable=False)

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

    # Eager (selectin) so variants are always loaded with the template: async
    # sessions cannot lazy-load, and the aggregate is never read without them.
    variants: Mapped[list[TemplateVariantModel]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="TemplateVariantModel.channel",
    )


class TemplateVariantModel(Base):
    """One channel's content for a template."""

    __tablename__ = "template_variants"

    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(actions) = 'array'",
            name="template_variants_actions_check",
        ),
        CheckConstraint(
            "jsonb_typeof(images) = 'array'",
            name="template_variants_images_check",
        ),
        CheckConstraint(
            "(body IS NOT NULL AND btrim(body) <> '') OR "
            "(html_body IS NOT NULL AND btrim(html_body) <> '')",
            name="template_variants_content_body_check",
        ),
    )

    template_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="CASCADE"),
        primary_key=True,
    )

    channel: Mapped[DeliveryChannel] = mapped_column(
        DeliveryChannelType,
        primary_key=True,
    )

    # ``NotificationContent.title``; the domain's ``validate_content`` decides
    # which channels require or forbid one.
    title: Mapped[str | None] = mapped_column(Text, nullable=True)

    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    html_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JSON arrays of {"label", "url"} and {"url", "alt"}. Never NULL: an empty
    # array is stored (asyncpg writes an explicit Python None as JSON null).
    actions: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    images: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    template: Mapped[TemplateModel] = relationship(back_populates="variants")
