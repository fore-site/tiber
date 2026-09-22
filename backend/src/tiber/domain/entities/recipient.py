import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..enums import DeliveryChannel
from ..value_objects import RecipientPreferences

# BCP-47-ish language tag: a 2-3 letter primary subtag (en, pt) optionally
# followed by script/region/variant subtags (en-US, zh-Hans, pt-BR). Tiber
# validates shape only; it never interprets what the tag selects.
_LANGUAGE_TAG_RE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")


@dataclass(frozen=True, kw_only=True)
class Recipient:
    """Recipient entity - the intended destination of a notification.

    Static profile facts (``timezone``, ``language``) are set once by the
    client and updated when they change (doc 08, D1) - they are facts about
    a person, so ``None`` means unknown, never a fabricated default. The
    ML layer's cold-start feature set reads them (doc 05); the domain
    itself never acts on them.
    """

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    addresses: dict[DeliveryChannel, str]
    preferences: RecipientPreferences
    external_id: str | None = None
    timezone: str | None = None
    language: str | None = None
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

        if self.timezone is not None:
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError) as e:
                raise ValueError(f"Invalid timezone: {self.timezone}") from e

        if self.language is not None and not _LANGUAGE_TAG_RE.fullmatch(self.language):
            raise ValueError(
                "Recipient language must be a language tag such as 'en' or "
                f"'pt-BR' (got: {self.language!r})"
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
        timezone: str | None = None,
        language: str | None = None,
    ) -> Recipient:
        """Create a new recipient with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            addresses=addresses,
            preferences=preferences,
            external_id=external_id,
            timezone=timezone,
            language=language,
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
        language: str | None,
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
            timezone=timezone,
            language=language,
            created_at=created_at,
            updated_at=updated_at,
            archived_at=archived_at,
        )

    def update_profile(
        self,
        *,
        timezone: str | None = None,
        language: str | None = None,
    ) -> Recipient:
        """Return a copy with the given profile facts set.

        Facts are provided, not patched: passing ``None`` records the fact
        as *unknown* (a client withdrawing a fact), distinct from "leave
        unchanged" - there is no        unchanged case, since the caller holds the
        full current profile and states what it is now. Validation runs in
        the constructor, so an invalid fact cannot be set.
        """
        return replace(
            self,
            timezone=timezone,
            language=language,
            updated_at=datetime.now(UTC),
        )
