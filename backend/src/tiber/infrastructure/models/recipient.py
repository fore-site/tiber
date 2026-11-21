from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RecipientModel(Base):
    """Notification recipients - destinations with channel-specific addresses."""

    __tablename__ = "recipients"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "external_id",
            name="recipients_project_external_id_unique",
        ),
        CheckConstraint(
            "jsonb_typeof(addresses) = 'object'",
            name="recipients_address_type_check",
        ),
        # A live recipient needs an identity or an address; a deleted one is a
        # scrubbed tombstone that keeps only its id and its history links.
        CheckConstraint(
            "external_id IS NOT NULL OR addresses != '{}'::jsonb "
            "OR deleted_at IS NOT NULL",
            name="recipients_identity_or_addresses",
        ),
        CheckConstraint(
            "jsonb_typeof(preferences) = 'object'",
            name="recipients_preferences_type_check",
        ),
        # Partial: the purge only ever scans tombstones, and live rows are the
        # overwhelming majority. Without it the hourly purge reads every
        # recipient in every project.
        Index(
            "ix_recipients_deleted_at",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
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

    external_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    addresses: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    # Consent state: opted-out channels and unsubscribed categories/topics.
    # Stored as an object rather than columns because it is one value object
    # and queries never filter on it. Quiet hours and blackout periods are
    # project-level delivery constraints, not recipient state.
    preferences: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # Static profile facts (doc 08, D1). Nullable: facts are unknown until
    # the client sets them, and ownerless auto-created profiles ship bare.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str | None] = mapped_column(String(35), nullable=True)

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

    # Soft delete: the row outlives the personal data because delivery history
    # references it. A scheduled purge removes it once history no longer blocks.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
