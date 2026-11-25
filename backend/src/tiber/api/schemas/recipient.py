from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...domain.entities import Recipient
from ...domain.enums import DeliveryChannel, NotificationCategory
from ...domain.value_objects import BlackoutPeriod, QuietHours
from ...domain.value_objects.preferences import UNSET, Unset
from .delivery_constraint import BlackoutPeriodModel, QuietHoursModel


class RecipientCreateRequest(BaseModel):
    """Fields accepted when registering a recipient."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_id: str = Field(min_length=1, max_length=255)
    addresses: dict[DeliveryChannel, str] = Field(default_factory=dict)

    @field_validator("addresses")
    @classmethod
    def addresses_are_valid(
        cls, addresses: dict[DeliveryChannel, str]
    ) -> dict[DeliveryChannel, str]:
        """Reject addresses with an empty destination."""
        if any(not address for address in addresses.values()):
            raise ValueError("addresses must not contain an empty value")
        return addresses


class RecipientUpdateRequest(BaseModel):
    """Replacement address book for a recipient."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    addresses: dict[DeliveryChannel, str]

    @field_validator("addresses")
    @classmethod
    def addresses_are_valid(
        cls, addresses: dict[DeliveryChannel, str]
    ) -> dict[DeliveryChannel, str]:
        """Reject addresses with an empty destination."""
        if any(not address for address in addresses.values()):
            raise ValueError("addresses must not contain an empty value")
        return addresses


class RecipientPreferencesRequest(BaseModel):
    """Partial delivery-preferences update for one recipient.

    An omitted consent list is left untouched; an explicit empty list clears
    it. That keeps repeated identical requests idempotent and stops an update
    of one set from silently erasing the other two. Time restrictions use the
    same partial rule: omitted leaves the stored value untouched, ``null``
    clears it, and an object replaces it.
    """

    model_config = ConfigDict(extra="forbid")

    opted_out_channels: list[DeliveryChannel] | None = None
    unsubscribed_categories: list[NotificationCategory] | None = None
    unsubscribed_topics: list[UUID] | None = None
    blackout_period: BlackoutPeriodModel | None = None
    quiet_hours: QuietHoursModel | None = None

    @field_validator(
        "opted_out_channels", "unsubscribed_categories", "unsubscribed_topics"
    )
    @classmethod
    def _no_duplicates(cls, values: list | None) -> list | None:
        """Reject duplicates instead of silently collapsing them."""
        if values is None:
            return None
        if len(set(values)) != len(values):
            raise ValueError("must not contain duplicates")
        return values

    @model_validator(mode="after")
    def _critical_is_always_deliverable(self) -> Self:
        """CRITICAL cannot be unsubscribed from, mirroring the domain rule."""
        if (
            self.unsubscribed_categories is not None
            and NotificationCategory.CRITICAL in self.unsubscribed_categories
        ):
            raise ValueError(
                "CRITICAL notifications are always deliverable and cannot be "
                "unsubscribed from."
            )
        return self

    def blackout_period_update(self) -> BlackoutPeriod | None | Unset:
        """Return the requested blackout change, or ``UNSET`` when omitted."""
        if "blackout_period" not in self.model_fields_set:
            return UNSET
        return self.blackout_period.to_domain() if self.blackout_period else None

    def quiet_hours_update(self) -> QuietHours | None | Unset:
        """Return the requested quiet-hours change, or ``UNSET`` when omitted."""
        if "quiet_hours" not in self.model_fields_set:
            return UNSET
        return self.quiet_hours.to_domain() if self.quiet_hours else None


class RecipientResponse(BaseModel):
    """API representation of a persisted recipient."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    external_id: str | None = None
    addresses: dict[str, str]
    opted_out_channels: list[DeliveryChannel]
    unsubscribed_categories: list[NotificationCategory]
    unsubscribed_topics: list[UUID]
    blackout_period: BlackoutPeriodModel | None = None
    quiet_hours: QuietHoursModel | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, recipient: Recipient) -> RecipientResponse:
        """Build the API representation from a domain recipient."""
        return cls(
            id=recipient.id,
            project_id=recipient.project_id,
            external_id=recipient.external_id,
            addresses={
                channel.value: address
                for channel, address in recipient.addresses.items()
            },
            opted_out_channels=sorted(recipient.preferences.opted_out_channels),
            unsubscribed_categories=sorted(
                recipient.preferences.unsubscribed_categories
            ),
            unsubscribed_topics=sorted(recipient.preferences.unsubscribed_topics),
            blackout_period=(
                BlackoutPeriodModel.from_domain(recipient.preferences.blackout_period)
                if recipient.preferences.blackout_period is not None
                else None
            ),
            quiet_hours=(
                QuietHoursModel.from_domain(recipient.preferences.quiet_hours)
                if recipient.preferences.quiet_hours is not None
                else None
            ),
            created_at=recipient.created_at,
            updated_at=recipient.updated_at,
        )


class RecipientListResponse(BaseModel):
    """One cursor page of project recipients."""

    data: list[RecipientResponse]
    next_cursor: str | None = None
