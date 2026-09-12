from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import DeliveryChannel


@dataclass(frozen=True, kw_only=True)
class Recipient:
    """Recipient entity - the intended destination of a notification."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    addresses: dict[str, str]
    opted_out_channels: list[DeliveryChannel] = field(default_factory=list)
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

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        addresses: dict[str, str],
        opted_out_channels: list[DeliveryChannel] | None = None,
        external_id: str | None = None,
    ) -> Recipient:
        """Create a new recipient with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            addresses=addresses,
            opted_out_channels=opted_out_channels or [],
            external_id=external_id,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        addresses: dict[str, str],
        opted_out_channels: list[DeliveryChannel],
        external_id: str | None,
        created_at: datetime,
        updated_at: datetime,
        archived_at: datetime | None,
    ) -> Recipient:
        """Rebuild an existing recipient from persisted state.

        Every field is required with no default: the stored row must supply
        identity and timestamps; nothing is silently regenerated.
        """
        return cls(
            id=id,
            project_id=project_id,
            addresses=addresses,
            opted_out_channels=opted_out_channels,
            external_id=external_id,
            created_at=created_at,
            updated_at=updated_at,
            archived_at=archived_at,
        )
