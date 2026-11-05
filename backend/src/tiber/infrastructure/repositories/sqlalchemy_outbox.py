"""SQLAlchemy adapter for the ``Outbox`` port (``application/ports/intake.py``).

Both methods insert a row in the CURRENT transaction and never commit. The row
becomes visible to the relay only when the unit of work commits, and it vanishes
with everything else if the unit of work rolls back. That is the whole point: the
state change and the announcement of it are atomic.

Call these only inside ``async with uow:``. A row written outside a block is flushed
immediately but belongs to an auto-begun transaction, which the next block discards
without warning; the unit of work's guard cannot see Core inserts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...application.ports.intake import OutboxPriority
from ...application.ports.outbox_relay import OutboxMessage
from ...domain.entities import Notification
from ...domain.entities.notification_intake import NotificationIntake
from ...domain.enums import NotificationCategory
from ...infrastructure.models.outbox import PRIORITY_RANK, OutboxKind, OutboxModel


class SQLAlchemyOutbox:
    """Writes outbox rows through the request's session.

    Satisfies the ``Outbox`` protocol structurally; no inheritance needed.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the outbox with the session shared with the unit of work."""
        self._session = session

    async def enqueue_intake(
        self, intake: NotificationIntake, *, priority: OutboxPriority
    ) -> None:
        """Announce an accepted request that a worker must expand.

        ``priority`` is chosen by the accept service (client-declared critical
        requests are ``"high"``).
        """
        await self._insert(
            kind=OutboxKind.INTAKE,
            aggregate_id=intake.id,
            priority=priority,
            payload={
                "intake_id": str(intake.id),
                "project_id": str(intake.project_id),
            },
        )

    async def enqueue_dispatch(self, notification: Notification) -> None:
        """Announce a notification that is ready to be delivered.

        * The caller only enqueues PENDING and POSTPONED notifications.
        * ``available_at`` is the notification's ``send_at`` (the resume time for a
          postponed one), so the relay publishes it when it is due. With no
          ``send_at`` it is due immediately.
        * Priority follows the category: critical notifications are published
          ahead of everything else.
        """
        is_critical = notification.category is NotificationCategory.CRITICAL
        await self._insert(
            kind=OutboxKind.DISPATCH,
            aggregate_id=notification.id,
            priority="high" if is_critical else "normal",
            payload={
                "notification_id": str(notification.id),
                "project_id": str(notification.project_id),
                # A routing hint, so the relay can pick a per-channel queue
                # without loading the notification.
                "channel": notification.channel.value,
            },
            available_at=notification.send_at,
        )

    async def claim_next(self, now: datetime) -> OutboxMessage | None:
        """Lock the next due outbox row without blocking other relay workers."""
        result = await self._session.execute(
            select(OutboxModel)
            .where(
                OutboxModel.published_at.is_(None),
                OutboxModel.dead_lettered_at.is_(None),
                OutboxModel.available_at <= now,
            )
            .order_by(
                OutboxModel.priority,
                OutboxModel.available_at,
                OutboxModel.id,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        if model.kind not in (OutboxKind.INTAKE.value, OutboxKind.DISPATCH.value):
            raise ValueError(f"Unknown outbox kind: {model.kind!r}")

        return OutboxMessage(
            id=model.id,
            kind=model.kind,
            aggregate_id=model.aggregate_id,
            payload=dict(model.payload),
            attempts=model.attempts,
        )

    async def mark_published(self, message_id: int, published_at: datetime) -> None:
        """Mark a locked row as published in the current transaction."""
        await self._session.execute(
            update(OutboxModel)
            .where(OutboxModel.id == message_id)
            .values(published_at=published_at, last_error=None)
        )

    async def mark_failed(
        self,
        message_id: int,
        *,
        failed_at: datetime,
        error: str,
        next_attempt_at: datetime | None,
    ) -> None:
        """Record an error and either schedule a retry or dead-letter the row."""
        values: dict[str, Any] = {
            "attempts": OutboxModel.attempts + 1,
            "last_error": error[:2000],
        }
        if next_attempt_at is None:
            values["dead_lettered_at"] = failed_at
        else:
            values["available_at"] = next_attempt_at
        await self._session.execute(
            update(OutboxModel).where(OutboxModel.id == message_id).values(**values)
        )

    async def _insert(
        self,
        *,
        kind: OutboxKind,
        aggregate_id: UUID,
        priority: OutboxPriority,
        payload: dict[str, Any],
        available_at: datetime | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "kind": kind.value,
            "aggregate_id": aggregate_id,
            "priority": PRIORITY_RANK[priority],
            "payload": payload,
        }
        # Leave ``available_at`` out when there is no send time so the database
        # default (now) applies.
        if available_at is not None:
            values["available_at"] = available_at

        # A plain INSERT statement, not ``session.add``: one statement, no identity
        # map bookkeeping, and any constraint error surfaces at this call.
        await self._session.execute(insert(OutboxModel).values(**values))
