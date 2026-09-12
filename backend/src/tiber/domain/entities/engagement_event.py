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

    @classmethod
    def create(
        cls,
        *,
        notification_id: UUID,
        project_id: UUID,
        recipient_id: UUID,
        event_type: EngagementEventType,
        channel: DeliveryChannel,
        provider: str,
        occurred_at: datetime,
        metadata: dict,
        is_synthetic: bool = False,
    ) -> EngagementEvent:
        """Create a new engagement event with a system-generated id and timestamps."""
        return cls(
            notification_id=notification_id,
            project_id=project_id,
            recipient_id=recipient_id,
            event_type=event_type,
            channel=channel,
            provider=provider,
            occurred_at=occurred_at,
            metadata=metadata,
            is_synthetic=is_synthetic,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        notification_id: UUID,
        project_id: UUID,
        recipient_id: UUID,
        event_type: EngagementEventType,
        channel: DeliveryChannel,
        provider: str,
        occurred_at: datetime,
        metadata: dict,
        is_synthetic: bool,
        created_at: datetime,
    ) -> EngagementEvent:
        """Rebuild an existing engagement event from persisted state."""
        return cls(
            id=id,
            notification_id=notification_id,
            project_id=project_id,
            recipient_id=recipient_id,
            event_type=event_type,
            channel=channel,
            provider=provider,
            occurred_at=occurred_at,
            metadata=metadata,
            is_synthetic=is_synthetic,
            created_at=created_at,
        )
