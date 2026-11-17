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
from .types import DeliveryChannel, DeliveryChannelType


class SenderIdentityModel(Base):
    """Project-owned From address backed by a provider domain."""

    __tablename__ = "sender_identities"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "channel",
            name="sender_identities_project_channel_unique",
        ),
        UniqueConstraint(
            "provider",
            "domain",
            name="sender_identities_provider_domain_unique",
        ),
        UniqueConstraint(
            "provider",
            "provider_domain_id",
            name="sender_identities_provider_domain_id_unique",
        ),
        CheckConstraint(
            "jsonb_typeof(dns_records) = 'array'",
            name="sender_identities_dns_records_check",
        ),
        Index("ix_sender_identities_project", "project_id"),
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

    channel: Mapped[DeliveryChannel] = mapped_column(
        DeliveryChannelType,
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    from_email: Mapped[str] = mapped_column(String(320), nullable=False)

    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    reply_to: Mapped[str | None] = mapped_column(String(320), nullable=True)

    domain: Mapped[str] = mapped_column(String(253), nullable=False)

    provider_domain_id: Mapped[str] = mapped_column(String(100), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    dns_records: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    verified_at: Mapped[datetime | None] = mapped_column(
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
