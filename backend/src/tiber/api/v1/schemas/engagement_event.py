from __future__ import annotations

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from tiber.domain.entities import EngagementEvent
from tiber.domain.enums import DeliveryChannel, EngagementEventType

# Provider-reported events (bounce, complaint, unsubscribe) carry authority that
# a client must not be able to claim on its own.
_CLIENT_REPORTABLE = frozenset({EngagementEventType.OPEN, EngagementEventType.CLICK})


class EngagementEventReportRequest(BaseModel):
    """A client-reported interaction, e.g. a push or in-app notification tap."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_type: EngagementEventType = Field(
        description="`open` or `click`; provider-only events are rejected.",
    )
    occurred_at: datetime = Field(
        description="When the interaction happened (timezone-aware).",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Opaque client context, stored as JSON.",
    )

    @field_validator("occurred_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        """Reject naive timestamps: they cannot be placed on a shared timeline."""
        if value.tzinfo is None:
            raise ValueError("`occurred_at` must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def _client_reportable(self) -> Self:
        """Only open and click may be self-reported by a client."""
        if self.event_type not in _CLIENT_REPORTABLE:
            raise ValueError(
                "Clients may report only `open` and `click` events; "
                "`bounce`, `complaint` and `unsubscribe` come from the provider."
            )
        return self


class EngagementEventResponse(BaseModel):
    """API representation of one recorded engagement event."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    notification_id: UUID
    project_id: UUID
    recipient_id: UUID | None = Field(
        description=(
            "Null once the recipient has been erased. The event itself is "
            "still recorded; only the attribution to a person is gone."
        ),
    )
    event_type: EngagementEventType
    channel: DeliveryChannel
    provider: str
    idempotency_key: str | None = None
    occurred_at: datetime
    metadata: dict[str, Any] | None = None
    is_synthetic: bool
    created_at: datetime

    @classmethod
    def from_entity(cls, event: EngagementEvent) -> EngagementEventResponse:
        """Build the API representation from a domain event."""
        return cls(
            id=event.id,
            notification_id=event.notification_id,
            project_id=event.project_id,
            recipient_id=event.recipient_id,
            event_type=event.event_type,
            channel=event.channel,
            provider=event.provider,
            idempotency_key=event.idempotency_key,
            occurred_at=event.occurred_at,
            metadata=event.metadata,
            is_synthetic=event.is_synthetic,
            created_at=event.created_at,
        )


class EngagementEventPageResponse(BaseModel):
    """One cursor page of engagement events."""

    model_config = ConfigDict(frozen=True)

    data: list[EngagementEventResponse]
    next_cursor: str | None = None
