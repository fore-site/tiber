from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .types import (
    DeliveryChannel,
    DeliveryChannelType,
    EngagementEventType,
    EngagementEventTypeType,
)


class EngagementEventModel(Base):
    """Recipient interaction reported after a notification was delivered.

    Events are append-only: the ML engine replays them and an edited training
    signal is worse than a missing one.

    The Python attribute is ``event_metadata`` because ``metadata`` is already
    taken on SQLAlchemy declarative classes; the database column keeps the
    domain name.
    """

    __tablename__ = "engagement_events"

    __table_args__ = (
        CheckConstraint(
            "metadata IS NULL OR jsonb_typeof(metadata) = 'object'",
            name="engagement_events_metadata_check",
        ),
        Index(
            "ix_engagement_events_project_occurred",
            "project_id",
            "occurred_at",
        ),
        Index("ix_engagement_events_notification", "notification_id"),
        Index("ix_engagement_events_recipient", "recipient_id"),
        Index(
            "uq_engagement_events_project_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    notification_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("notifications.id", ondelete="RESTRICT"),
        nullable=False,
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    )

    recipient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recipients.id", ondelete="RESTRICT"),
        nullable=False,
    )

    event_type: Mapped[EngagementEventType] = mapped_column(
        EngagementEventTypeType,
        nullable=False,
    )

    channel: Mapped[DeliveryChannel] = mapped_column(
        DeliveryChannelType,
        nullable=False,
    )

    # The provider that reported the event ("resend", "fcm", or "client" for
    # events reported by a customer application).
    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Client-supplied dedupe key. Provider-ingested events leave it NULL, and
    # Postgres allows many NULLs in a unique index, so only client reports are
    # constrained.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    event_metadata: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    # Synthetic rows feed model bootstrapping and must never be mixed into a
    # training run with real signals.
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
