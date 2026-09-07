from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from ..enums import DeliveryChannel, EngagementEventType


@dataclass(frozen=True)
class EngagementEvent:
    """Domain entity representing recipient interaction reported by delivery providers."""

    id: UUID
    notification_id: UUID
    project_id: UUID
    recipient_id: UUID
    event_type: EngagementEventType
    channel: DeliveryChannel
    provider: str
    occurred_at: datetime
    metadata: dict
    is_synthetic: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
