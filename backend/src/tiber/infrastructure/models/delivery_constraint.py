from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DeliveryConstraintModel(Base):
    """Project-level delivery constraint (quiet hours, blackout periods).

    One row per project: configuration read whole for policy evaluation,
    never queried by window. The window lists are JSONB because they are
    configuration payloads validated by the domain value objects on
    rehydration — not queried, joined, or aggregated in SQL.
    """

    __tablename__ = "delivery_constraints"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    blackout_periods: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
    )

    quiet_hours: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
    )

    timezone: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="UTC",
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
