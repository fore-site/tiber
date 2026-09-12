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
    attempt_number: int
    status: DeliveryAttemptStatus
    channel: DeliveryChannel
    provider: str
    provider_message_id: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the delivery attempt's state after initialization."""
        if self.attempt_number <= 0:
            raise ValueError("DeliveryAttempt attempt_number must be positive")
        if not self.provider or not self.provider.strip():
            raise ValueError("DeliveryAttempt provider must not be empty")
