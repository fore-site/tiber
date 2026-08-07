"""Stable, serializable job payload carried by Celery notification tasks.

The payload is the contract between the API service (publisher) and the worker.
It is self-contained, JSON-serializable metadata describing one delivery job:
identity (``notification_id``/``project_id``/``recipient_id``), tracing
(``correlation_id``), scheduling metadata (``scheduled_at``/``send_time_basis``),
the ``schema_version`` guarding message-body migrations, and bounded ``retry``
state. The worker re-reads authoritative state from the database and uses the
payload for routing, tracing, and retry bookkeeping.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..domain.entities import Notification
from ..domain.enums import DeliveryChannel, SendTimeBasis

SCHEMA_VERSION = 1


class RetryState(BaseModel):
    """Bounded retry bookkeeping carried inside the job payload.

    ``attempt`` counts completed/prior delivery attempts; ``max_attempts`` is
    the hard ceiling. ``is_exhausted`` is the single source of truth for the
    "give up and dead-letter" decision, keeping the bound unit-testable apart
    from Celery plumbing.
    """

    model_config = ConfigDict(frozen=True)

    attempt: int = Field(default=0, ge=0, description="Prior delivery attempts.")
    max_attempts: int = Field(
        default=4,
        ge=1,
        description="Hard ceiling on delivery attempts.",
    )

    def next_attempt(self) -> RetryState:
        """Return a copy advanced to the next attempt."""
        return RetryState(attempt=self.attempt + 1, max_attempts=self.max_attempts)

    def is_exhausted(self) -> bool:
        """Return True once the attempt ceiling has been reached."""
        return self.attempt >= self.max_attempts


class NotificationJobPayload(BaseModel):
    """Self-contained metadata for one notification delivery job."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = SCHEMA_VERSION
    notification_id: UUID
    project_id: UUID
    recipient_id: UUID
    correlation_id: UUID
    channel: DeliveryChannel
    scheduled_at: datetime | None = None
    send_time_basis: SendTimeBasis = SendTimeBasis.IMMEDIATE
    retry: RetryState = Field(default_factory=RetryState)

    @classmethod
    def from_entity(cls, notification: Notification) -> NotificationJobPayload:
        """Build the job payload for an already-persisted notification."""
        return cls(
            notification_id=notification.id,
            project_id=notification.project_id,
            recipient_id=notification.recipient_id,
            correlation_id=notification.correlation_id,
            channel=notification.channel,
            scheduled_at=notification.scheduled_at,
            send_time_basis=notification.send_time_basis,
        )

    @property
    def routing_key(self) -> str:
        """Channel-scoped routing key used to place the job on the broker."""
        return f"notification.{self.channel.value}"

    def to_json_dict(self) -> dict:
        """Return a JSON-serializable dict for ``apply_async(args=[...])``."""
        return self.model_dump(mode="json")
