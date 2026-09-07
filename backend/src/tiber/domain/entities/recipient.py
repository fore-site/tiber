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
    opted_out_channels: list[str] = field(default_factory=list)
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

        # validate opted_out channels
        normalized_opted_out_channels = list(
            dict.fromkeys(
                DeliveryChannel(channel.lower()).value
                for channel in self.opted_out_channels
            )
        )

        unavailable_channels = set(normalized_opted_out_channels) - set(
            normalized_addresses
        )
        if unavailable_channels:
            raise ValueError(
                "Recipient opted-out channels must have configured destination addresses: "
                f"{sorted(unavailable_channels)}"
            )

        object.__setattr__(self, "addresses", normalized_addresses)
        object.__setattr__(self, "opted_out_channels", normalized_opted_out_channels)
