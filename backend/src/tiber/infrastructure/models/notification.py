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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .types import (
    DeliveryChannel,
    DeliveryChannelType,
    NotificationStatus,
    NotificationStatusType,
    SendTimeBasis,
    SendTimeBasisType,
)


class NotificationModel(Base):
    """Immutable notification accepted by Tiber."""

    __tablename__ = "notifications"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="notifications_project_idempotency_key_unique",
        ),
        CheckConstraint(
            """
            template_variables IS NULL
            OR jsonb_typeof(template_variables) = 'object'
            """,
            name="notifications_template_variables_check",
        ),
        CheckConstraint(
            """
            (
                status = 'policy_rejected'
                AND policy_violation_reason IS NOT NULL
            )
            OR
            (
                status <> 'policy_rejected'
                AND policy_violation_reason IS NULL
            )
            """,
            name="notifications_policy_violation_check",
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

    channel: Mapped[DeliveryChannel] = mapped_column(
        DeliveryChannelType,
        nullable=False,
    )

    status: Mapped[NotificationStatus] = mapped_column(
        NotificationStatusType,
        nullable=False,
        server_default="pending",
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        nullable=True,
    )

    correlation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
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

    template_variables: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    send_time_basis: Mapped[SendTimeBasis] = mapped_column(
        SendTimeBasisType,
        nullable=False,
        server_default="immediate",
    )

    policy_violation_reason: Mapped[str | None] = mapped_column(
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
