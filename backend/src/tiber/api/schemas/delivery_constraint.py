from __future__ import annotations

from datetime import datetime, time
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...domain.entities import DeliveryConstraint
from ...domain.enums import DeliveryChannel
from ...domain.value_objects import BlackoutPeriod, QuietHours


class BlackoutPeriodModel(BaseModel):
    """A single absolute delivery blackout."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _valid_period(self) -> Self:
        """Reuse the domain invariant instead of duplicating it."""
        BlackoutPeriod(name=self.name, start=self.start, end=self.end)
        return self

    def to_domain(self) -> BlackoutPeriod:
        """Build the domain value object."""
        return BlackoutPeriod(name=self.name, start=self.start, end=self.end)

    @classmethod
    def from_domain(cls, period: BlackoutPeriod) -> BlackoutPeriodModel:
        """Build the API representation from a domain value object."""
        return cls(name=period.name, start=period.start, end=period.end)


class QuietHoursModel(BaseModel):
    """A recurring time-of-day restriction for one delivery channel."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    window_start: time
    window_end: time
    channel: DeliveryChannel
    description: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _valid_window(self) -> Self:
        """Reuse the domain invariant instead of duplicating it."""
        QuietHours(
            name=self.name,
            window_start=self.window_start,
            window_end=self.window_end,
            channel=self.channel,
            description=self.description,
        )
        return self

    def to_domain(self) -> QuietHours:
        """Build the domain value object."""
        return QuietHours(
            name=self.name,
            window_start=self.window_start,
            window_end=self.window_end,
            channel=self.channel,
            description=self.description,
        )

    @classmethod
    def from_domain(cls, window: QuietHours) -> QuietHoursModel:
        """Build the API representation from a domain value object."""
        return cls(
            name=window.name,
            window_start=window.window_start,
            window_end=window.window_end,
            channel=window.channel,
            description=window.description,
        )


class DeliveryConstraintUpdateRequest(BaseModel):
    """Full replacement of a project's delivery constraint.

    The resource is a singleton per project, so ``PUT`` states the complete
    configuration: an omitted list clears it. The timezone is required because
    quiet-hours evaluation is meaningless without stating the wall clock it
    refers to.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    timezone: str
    blackout_periods: list[BlackoutPeriodModel] = Field(default_factory=list)
    quiet_hours: list[QuietHoursModel] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        """Reject unknown IANA zone names before they reach the entity."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone: {value!r}") from exc
        return value


class DeliveryConstraintResponse(BaseModel):
    """API representation of a project's delivery constraint."""

    model_config = ConfigDict(frozen=True)

    timezone: str
    blackout_periods: list[BlackoutPeriodModel]
    quiet_hours: list[QuietHoursModel]

    @classmethod
    def from_entity(cls, constraint: DeliveryConstraint) -> DeliveryConstraintResponse:
        """Build the API representation from a domain delivery constraint."""
        return cls(
            timezone=constraint.timezone,
            blackout_periods=[
                BlackoutPeriodModel.from_domain(period)
                for period in constraint.blackout_periods
            ],
            quiet_hours=[
                QuietHoursModel.from_domain(window) for window in constraint.quiet_hours
            ],
        )
