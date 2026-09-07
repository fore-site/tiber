from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from ..enums import DeliveryChannel


@dataclass(frozen=True)
class Recipient:
    """Recipient entity - the intended destination of a notification."""

    id: UUID
    project_id: UUID
    addresses: dict[str, str]
    external_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the recipient's state after initialization."""
        if not self.addresses:
            raise ValueError("Recipient addresses must not be empty")

        # Validate address keys
        normalized_addresses = {
            DeliveryChannel(key.lower()).value: value
            for key, value in self.addresses.items()
        }

        object.__setattr__(self, "addresses", normalized_addresses)
