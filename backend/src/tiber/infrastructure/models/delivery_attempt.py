from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .types import (
    DeliveryAttemptStatus,
    DeliveryAttemptStatusType,
    DeliveryChannel,
    DeliveryChannelType,
)


class DeliveryAttemptModel(Base):
    """Immutable record of each delivery attempt. Never updated or deleted."""

    __tablename__ = "delivery_attempts"

    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "attempt_number",
            name="delivery_attempts_notification_attempt_unique",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="delivery_attempts_attempt_number_check",
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

    attempt_number: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )

    status: Mapped[DeliveryAttemptStatus] = mapped_column(
        DeliveryAttemptStatusType,
        nullable=False,
    )

    channel: Mapped[DeliveryChannel] = mapped_column(
        DeliveryChannelType,
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    provider_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
