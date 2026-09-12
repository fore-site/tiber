from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import DeliveryChannel, EngagementEventType


@dataclass(frozen=True, kw_only=True)
class EngagementEvent:
    """Domain entity representing recipient interaction reported by delivery providers."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
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
