from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import DeliveryAttemptStatus, DeliveryChannel


@dataclass(frozen=True, kw_only=True)
class DeliveryAttempt:
    """DeliveryAttempt entity - a single immutable attempt to deliver a notification.

    Attempts are immutable records: retries generate additional attempts rather
    than mutating existing ones.
    """

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    notification_id: UUID
    status: DeliveryAttemptStatus
    channel: DeliveryChannel
    provider: str
    recipient_address: str | None = None
    provider_message_id: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the delivery attempt's state after initialization."""
        # Boundary coercion before any validation reads the fields.
        object.__setattr__(self, "status", DeliveryAttemptStatus(self.status.lower()))
        object.__setattr__(self, "channel", DeliveryChannel(self.channel.lower()))

        if not self.provider or not self.provider.strip():
            raise ValueError("DeliveryAttempt provider must not be empty")

        # A success means something was contacted: the snapshot cannot be
        # empty. A failure may precede any contact (no address on file),
        # so None is only legal there.
        if (
            self.status is DeliveryAttemptStatus.SUCCESS
            and self.recipient_address is None
        ):
            raise ValueError(
                "DeliveryAttempt.recipient_address is required when status is success."
            )

    @classmethod
    def create(
        cls,
        *,
        notification_id: UUID,
        status: DeliveryAttemptStatus,
        channel: DeliveryChannel,
        provider: str,
        recipient_address: str | None = None,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> DeliveryAttempt:
        """Record a new delivery attempt with a system-generated id and timestamp."""
        return cls(
            notification_id=notification_id,
            status=status,
            channel=channel,
            provider=provider,
            recipient_address=recipient_address,
            provider_message_id=provider_message_id,
            error=error,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        notification_id: UUID,
        status: DeliveryAttemptStatus,
        channel: DeliveryChannel,
        provider: str,
        recipient_address: str | None,
        provider_message_id: str | None,
        error: str | None,
        created_at: datetime,
    ) -> DeliveryAttempt:
        """Rebuild an existing delivery attempt from persisted state."""
        return cls(
            id=id,
            notification_id=notification_id,
            status=status,
            channel=channel,
            provider=provider,
            recipient_address=recipient_address,
            provider_message_id=provider_message_id,
            error=error,
            created_at=created_at,
        )
