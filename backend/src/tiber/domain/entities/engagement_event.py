from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import DeliveryChannel, EngagementEventType
from ..exceptions import InvalidEntityAttributeError


@dataclass(frozen=True, kw_only=True)
class EngagementEvent:
    """Domain entity representing a recipient interaction.

    Events come from two sources: delivery providers (opens, clicks, bounces,
    complaints, unsubscribes) and client applications (push and in-app taps).
    Client-reported rows may carry an idempotency key so a retried report does
    not duplicate a training signal.
    """

    id: UUID = field(default_factory=uuid4)
    notification_id: UUID
    project_id: UUID
    # NULL once the recipient has been purged. The interaction still happened,
    # and the row is still a training signal, but it no longer names anyone.
    recipient_id: UUID | None
    event_type: EngagementEventType
    channel: DeliveryChannel
    provider: str
    # Client-supplied dedupe key. Provider-reported events leave it None.
    idempotency_key: str | None = None
    occurred_at: datetime
    metadata: dict | None = None
    is_synthetic: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Reject an idempotency key that cannot identify one report."""
        if self.idempotency_key is None:
            return
        if not self.idempotency_key.strip():
            raise InvalidEntityAttributeError(
                "`idempotency_key` must be a non-empty string when provided"
            )
        if len(self.idempotency_key) > 255:
            raise InvalidEntityAttributeError(
                "`idempotency_key` must be at most 255 characters"
            )

    @classmethod
    def create(
        cls,
        *,
        notification_id: UUID,
        project_id: UUID,
        recipient_id: UUID | None,
        event_type: EngagementEventType,
        channel: DeliveryChannel,
        provider: str,
        idempotency_key: str | None = None,
        occurred_at: datetime,
        metadata: dict | None = None,
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
            idempotency_key=idempotency_key,
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
        recipient_id: UUID | None,
        event_type: EngagementEventType,
        channel: DeliveryChannel,
        provider: str,
        idempotency_key: str | None,
        occurred_at: datetime,
        metadata: dict | None = None,
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
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            metadata=metadata,
            is_synthetic=is_synthetic,
            created_at=created_at,
        )
