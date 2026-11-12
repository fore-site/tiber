from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ...domain.entities import DeliveryAttempt
from ...domain.enums import DeliveryAttemptStatus, DeliveryChannel


class DeliveryAttemptResponse(BaseModel):
    """API representation of one immutable delivery attempt.

    ``recipient_address`` is the dispatch-time snapshot: what the provider was
    actually given, which may differ from the recipient's current profile.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    notification_id: UUID
    attempt_number: int
    status: DeliveryAttemptStatus
    channel: DeliveryChannel
    provider: str
    recipient_address: str | None = None
    provider_message_id: str | None = None
    error: str | None = None
    created_at: datetime

    @classmethod
    def from_entity(cls, attempt: DeliveryAttempt) -> DeliveryAttemptResponse:
        """Build the API representation from a domain attempt."""
        return cls(
            id=attempt.id,
            notification_id=attempt.notification_id,
            attempt_number=attempt.attempt_number,
            status=attempt.status,
            channel=attempt.channel,
            provider=attempt.provider,
            recipient_address=attempt.recipient_address,
            provider_message_id=attempt.provider_message_id,
            error=attempt.error,
            created_at=attempt.created_at,
        )


class DeliveryAttemptPageResponse(BaseModel):
    """One cursor page of delivery attempts."""

    model_config = ConfigDict(frozen=True)

    data: list[DeliveryAttemptResponse]
    next_cursor: str | None = None
