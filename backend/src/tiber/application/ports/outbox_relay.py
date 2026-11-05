"""Ports for draining the transactional outbox."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

OutboxKind = Literal["intake", "dispatch"]


@dataclass(frozen=True)
class OutboxMessage:
    """A claimed outbox row with the data needed to publish it."""

    id: int
    kind: OutboxKind
    aggregate_id: UUID
    payload: dict[str, object]
    attempts: int


class OutboxRelayRepository(Protocol):
    """Persistence operations used by the outbox relay."""

    async def claim_next(self, now: datetime) -> OutboxMessage | None:
        """Lock and return the next due, unpublished outbox message."""
        ...

    async def mark_published(self, message_id: int, published_at: datetime) -> None:
        """Record successful publication of a locked message."""
        ...

    async def mark_failed(
        self,
        message_id: int,
        *,
        failed_at: datetime,
        error: str,
        next_attempt_at: datetime | None,
    ) -> None:
        """Record a publication failure and retry time, or dead-letter it."""
        ...
