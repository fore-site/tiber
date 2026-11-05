"""Transactional outbox table.

A row is written in the SAME transaction as the state change it announces (the
intake, the notifications), so either both exist or neither does. A separate relay
later publishes unpublished rows to the broker. This closes the gap where a commit
succeeds but the publish never happens.

Contract for the relay (not part of this module)
------------------------------------------------
* Poll with ``published_at IS NULL AND available_at <= now()``, ordered by
  ``priority, available_at, id``, using ``FOR UPDATE SKIP LOCKED`` so several relay
  instances can run side by side.
* Never poll with an ``id`` cursor ("everything after the last id I saw"). Ids are
  assigned at insert time but become visible at commit time, so a row with a lower
  id can commit after a higher one and would be skipped forever.
* Delivery is at-least-once: a relay can crash after publishing and before marking
  the row. Consumers must therefore be idempotent. (``mark_processing`` on the
  notification and the intake claim already are.)
* Rows carry ids, not state. The consumer loads the entity by id.
* Published rows are never deleted by the adapter; run a retention job.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OutboxKind(StrEnum):
    """What a row announces."""

    INTAKE = "intake"  # an accepted request that a worker must expand
    DISPATCH = "dispatch"  # a notification that is ready to be delivered


# Stored as a small integer so ordering by the column is correct by construction
# (0 sorts first) instead of depending on how the words "high" and "normal" sort.
PRIORITY_HIGH = 0
PRIORITY_NORMAL = 1
PRIORITY_RANK: dict[str, int] = {"high": PRIORITY_HIGH, "normal": PRIORITY_NORMAL}


class OutboxModel(Base):
    """One message waiting to be published to the broker."""

    __tablename__ = "outbox"

    __table_args__ = (
        CheckConstraint("kind IN ('intake', 'dispatch')", name="outbox_kind_check"),
        CheckConstraint("priority IN (0, 1)", name="outbox_priority_check"),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="outbox_payload_check"
        ),
        # The relay's work queue. Partial, so it only ever holds unpublished rows
        # and stays small however large the table grows.
        Index(
            "ix_outbox_unpublished",
            "priority",
            "available_at",
            "id",
            postgresql_where=text("published_at IS NULL AND dead_lettered_at IS NULL"),
        ),
        Index("ix_outbox_aggregate", "aggregate_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )

    kind: Mapped[str] = mapped_column(Text, nullable=False)

    # The intake id or notification id this row is about. Deliberately NOT a
    # foreign key: the outbox must stay independent of the tables it announces.
    aggregate_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )

    priority: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=text("1"),
    )

    # Ids and routing hints only; never a copy of entity state.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Not published before this instant. A scheduled or postponed notification sets
    # it to its send time, so the relay can hold it in the database instead of
    # parking it in the broker (long broker-side delays are unreliable on some
    # brokers).
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relay bookkeeping, for retry limits and finding poison messages.
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
