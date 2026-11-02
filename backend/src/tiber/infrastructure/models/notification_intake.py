"""SQLAlchemy model for accepted notification requests."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .types import IntakeStatusType


class NotificationIntakeModel(Base):
    """A validated request waiting to be expanded into notifications."""

    __tablename__ = "notification_intakes"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "transaction_id",
            name="notification_intakes_project_transaction_unique",
        ),
        Index(
            "notification_intakes_project_idempotency_unique",
            "project_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_notification_intakes_project_created",
            "project_id",
            "created_at",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="notification_intakes_payload_check",
        ),
        CheckConstraint(
            "jsonb_typeof(constraints) = 'object'",
            name="notification_intakes_constraints_check",
        ),
        CheckConstraint(
            "plan IS NULL OR jsonb_typeof(plan) = 'object'",
            name="notification_intakes_plan_check",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="notification_intakes_attempts_check",
        ),
        CheckConstraint(
            """
            (
                status = 'processing'
                AND claimed_at IS NOT NULL
            )
            OR status <> 'processing'
            """,
            name="notification_intakes_processing_claim_check",
        ),
        CheckConstraint(
            """
            (
                status = 'received'
                AND plan IS NULL
                AND claimed_at IS NULL
                AND completed_at IS NULL
            )
            OR status <> 'received'
            """,
            name="notification_intakes_received_check",
        ),
        CheckConstraint(
            """
            (
                status = 'completed'
                AND plan IS NOT NULL
                AND completed_at IS NOT NULL
            )
            OR status <> 'completed'
            """,
            name="notification_intakes_completed_check",
        ),
        CheckConstraint(
            "completed_at IS NULL OR status = 'completed'",
            name="notification_intakes_completed_at_check",
        ),
        CheckConstraint(
            """
            (
                status = 'failed'
                AND failure_reason IS NOT NULL
            )
            OR
            (
                status <> 'failed'
                AND failure_reason IS NULL
            )
            """,
            name="notification_intakes_failure_check",
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

    transaction_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )

    recipient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recipients.id", ondelete="RESTRICT"),
        nullable=False,
    )

    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)

    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # These are immutable snapshots of the validated request and the choices the
    # worker is allowed to make. Keeping them together avoids reconstructing
    # accept-time state from mutable templates, topics, or recipient settings.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    constraints: Mapped[dict] = mapped_column(JSONB, nullable=False)
    plan: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        IntakeStatusType,
        nullable=False,
        server_default="received",
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

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
