from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
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
    NotificationCategory,
    NotificationCategoryType,
    NotificationStatus,
    NotificationStatusType,
    SendTimeBasis,
    SendTimeBasisType,
)


class NotificationModel(Base):
    """A single-channel notification.

    One request fans out into one row per channel; the rows share a
    ``correlation_id`` and the client's ``idempotency_key``.
    """

    __tablename__ = "notifications"

    __table_args__ = (
        # One notification per channel per request. Replaces the former
        # (project_id, idempotency_key) uniqueness: children of one request all
        # carry the client's key, and the intake table now owns idempotency.
        # Its leading columns also serve the batch lookup by correlation_id.
        UniqueConstraint(
            "project_id",
            "correlation_id",
            "channel",
            name="notifications_project_correlation_channel_unique",
        ),
        Index("ix_notifications_project_created", "project_id", "created_at"),
        CheckConstraint(
            """
            template_variables IS NULL
            OR jsonb_typeof(template_variables) = 'object'
            """,
            name="notifications_template_variables_check",
        ),
        CheckConstraint(
            "jsonb_typeof(actions) = 'array'",
            name="notifications_actions_check",
        ),
        CheckConstraint(
            "jsonb_typeof(images) = 'array'",
            name="notifications_images_check",
        ),
        CheckConstraint(
            """
            (
                status = 'suppressed'
                AND suppression_reason IS NOT NULL
            )
            OR
            (
                status <> 'suppressed'
                AND suppression_reason IS NULL
            )
            """,
            name="notifications_suppression_reason_check",
        ),
        CheckConstraint(
            """
            (
                channel = 'email'
                AND subject IS NOT NULL
            )
            OR
            (
                channel <> 'email'
                AND subject IS NULL
            )
            """,
            name="notifications_subject_check",
        ),
        CheckConstraint(
            """
            (
                status IN ('failed', 'bounced')
                AND failure_reason IS NOT NULL
            )
            OR
            (
                status NOT IN ('failed', 'bounced')
                AND failure_reason IS NULL
            )
            """,
            name="notifications_failure_reason_check",
        ),
        CheckConstraint(
            """
            (
                status = 'postponed'
                AND send_at IS NOT NULL
            )
            OR
            (
                status <> 'postponed'
            )
            """,
            name="notifications_postponed_send_at_check",
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

    recipient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recipients.id", ondelete="RESTRICT"),
        nullable=False,
    )

    template_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="SET NULL"),
        nullable=True,
    )

    topic_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="SET NULL"),
        nullable=True,
    )

    channel: Mapped[DeliveryChannel] = mapped_column(
        DeliveryChannelType,
        nullable=False,
    )

    category: Mapped[NotificationCategory] = mapped_column(
        NotificationCategoryType,
        nullable=False,
    )

    status: Mapped[NotificationStatus] = mapped_column(
        NotificationStatusType,
        nullable=False,
        server_default="pending",
    )

    # The client's key, shared by every notification of one request. Not unique
    # here; uniqueness is (project_id, correlation_id, channel) above.
    idempotency_key: Mapped[str | None] = mapped_column(
        nullable=True,
    )

    # Client-supplied identity of the logical thing this send is about,
    # shared across related sends. Opaque: stored and indexed, never parsed.
    # Indexed with recipient because the first recorded consumer is the
    # per-(recipient, group_key) engagement-history query.
    group_key: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    correlation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )

    # ``NotificationContent.title``. Kept under the email-specific column name
    # because the check constraint above ties it to the email channel.
    subject: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # ``NotificationContent.actions`` / ``.images`` as JSON arrays of
    # {"label", "url"} and {"url", "alt"}. Never NULL: an empty array is stored
    # (asyncpg would write an explicit Python None as JSON null, not SQL NULL).
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

    template_variables: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    send_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    send_time_basis: Mapped[SendTimeBasis] = mapped_column(
        SendTimeBasisType,
        nullable=False,
        server_default="immediate",
    )

    suppression_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
