from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class WebhookEndpointModel(Base):
    """A client-registered callback destination.

    Only the API Service writes here. The Worker Service reads the same rows
    when it dispatches lifecycle events, so this table is the hand-off point
    between registration and firing.
    """

    __tablename__ = "webhook_endpoints"

    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(events) = 'array'",
            name="webhook_endpoints_events_check",
        ),
        Index("ix_webhook_endpoints_project", "project_id"),
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

    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Stored as a JSON array of WebhookEventType values. An array column would
    # need a second enum type; the values already travel as strings on the wire.
    events: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    # The signing key is recoverable by design (the dispatcher must reproduce
    # the HMAC), so it is encrypted, never hashed. See core.encryption.
    encrypted_signing_secret: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Non-sensitive display aid so a client can tell two secrets apart.
    secret_prefix: Mapped[str] = mapped_column(
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
