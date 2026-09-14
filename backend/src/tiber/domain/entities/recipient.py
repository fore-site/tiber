from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import DeliveryChannel
from ..value_objects import RecipientPreferences


@dataclass(frozen=True, kw_only=True)
class Recipient:
    """Recipient entity - the intended destination of a notification."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    addresses: dict[DeliveryChannel, str]
    preferences: RecipientPreferences
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
            DeliveryChannel(key.lower()): value for key, value in self.addresses.items()
        }

        opted_out_channels = self.preferences.opted_out_channels
        unavailable_channels = set(opted_out_channels) - set(normalized_addresses)
        if unavailable_channels:
            raise ValueError(
                "Recipient opted-out channels must have configured destination addresses: "
                f"{sorted(unavailable_channels)}"
            )

        object.__setattr__(self, "addresses", normalized_addresses)

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        addresses: dict[DeliveryChannel, str],
        preferences: RecipientPreferences,
        external_id: str | None = None,
    ) -> Recipient:
        """Create a new recipient with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            addresses=addresses,
            preferences=preferences,
            external_id=external_id,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        addresses: dict[DeliveryChannel, str],
        preferences: RecipientPreferences,
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
            preferences=preferences,
            external_id=external_id,
            created_at=created_at,
            updated_at=updated_at,
            archived_at=archived_at,
        )
