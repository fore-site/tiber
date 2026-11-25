from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..enums import DeliveryChannel
from ..exceptions import InvalidEntityAttributeError
from ..value_objects import RecipientPreferences


@dataclass(frozen=True, kw_only=True)
class Recipient:
    """Recipient entity - the intended destination of a notification.

    Static profile facts (``timezone``) are set once by the client and updated
    when they change - they are facts about a person, so ``None`` means
    unknown.
    """

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    addresses: dict[DeliveryChannel, str]
    preferences: RecipientPreferences
    external_id: str | None = None
    timezone: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the recipient's state after initialization."""
        if self.deleted_at is not None:
            # A deleted recipient is a tombstone: its personal data has been
            # scrubbed, so the invariants below describe live recipients only.
            return

        if not self.addresses and not self.external_id:
            raise InvalidEntityAttributeError(
                "Recipient needs at least one address or an external_id"
            )

        opted_out_channels = self.preferences.opted_out_channels
        unavailable_channels = set(opted_out_channels) - set(self.addresses)
        if unavailable_channels:
            raise ValueError(
                "Recipient opted-out channels must have configured destination addresses: "
                f"{sorted(unavailable_channels)}"
            )

        if self.timezone is not None:
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError) as e:
                raise InvalidEntityAttributeError(
                    f"Invalid timezone: {self.timezone}"
                ) from e

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        addresses: dict[DeliveryChannel, str],
        preferences: RecipientPreferences | None = None,
        external_id: str | None = None,
        timezone: str | None = None,
    ) -> Recipient:
        """Create a new recipient with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            addresses=addresses,
            preferences=preferences or RecipientPreferences(),
            external_id=external_id,
            timezone=timezone,
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
        timezone: str | None,
        created_at: datetime,
        updated_at: datetime,
        deleted_at: datetime | None,
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
            timezone=timezone,
            created_at=created_at,
            updated_at=updated_at,
            deleted_at=deleted_at,
        )

    def claim(
        self, external_id: str, addresses: dict[DeliveryChannel, str]
    ) -> Recipient:
        """Attach a human identity and its addresses.

        Merges the incoming addresses over the existing ones (incoming wins
        on key collision) and stamps ``external_id``. Preconditions:

        - ``external_id`` must be non-empty.
        - The recipient must be ownerless: a claimed recipient cannot be
          re-claimed. Uniqueness of ``(project_id, external_id)`` across
          recipients is a database guarantee; this only enforces the
          single-recipient invariant.
        - The merged state must stay valid (post_init): every opted-out
          channel must retain an address after the merge.

        Registration with an address owned by a *different registered*
        recipient is a caller-visible conflict; the domain
        cannot detect it - the caller queries first, and the database
        constraint backs the race.
        """
        if not external_id or not external_id.strip():
            raise ValueError("external_id must be a non-empty string")
        if self.external_id is not None:
            raise ValueError("Recipient is already claimed and cannot be re-claimed")

        # Merge is never empty: self.addresses is non-empty by invariant.
        merged = {**self.addresses, **addresses}
        return replace(
            self,
            external_id=external_id.strip(),
            addresses=merged,
            updated_at=datetime.now(UTC),
        )

    def update_addresses(self, addresses: dict[DeliveryChannel, str]) -> Recipient:
        """Return a copy with the given addresses replacing the old set.

        The incoming mapping is the full new address book; an omitted
        channel is removed.
        """
        if not addresses and not self.external_id:
            raise ValueError(
                "Addresses must not be empty for an unregistered recipient"
            )
        return replace(self, addresses=addresses, updated_at=datetime.now(UTC))

    def update_preferences(self, preferences: RecipientPreferences) -> Recipient:
        """Return a copy with new consent state; stamps updated_at."""
        return replace(self, preferences=preferences, updated_at=datetime.now(UTC))

    def update_timezone(self, timezone: str | None) -> Recipient:
        """Restate the recipient's timezone.

        ``None`` records the fact as *unknown* (withdrawal), which is a
        deliberate semantic, not a missing argument.
        """
        return replace(self, timezone=timezone, updated_at=datetime.now(UTC))

    def delete(self) -> Recipient:
        """Return a deleted copy with the personal data scrubbed.

        The row is kept (``deleted_at`` marks it) because delivery history holds
        foreign keys to it, so the personal data cannot wait for the eventual
        purge: identity, contact addresses and profile facts are dropped here,
        in the same copy that marks the recipient deleted.

        Consent state is preserved, because it is not personal data and it is
        the record that this person opted out. It survives only as long as the
        tombstone: the purge removes the row (and with it the opt-outs) after
        the grace period.
        """
        now = datetime.now(UTC)
        return replace(
            self,
            external_id=None,
            addresses={},
            timezone=None,
            deleted_at=now,
            updated_at=now,
        )
