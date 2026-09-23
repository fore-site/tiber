from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..value_objects import BlackoutPeriod, RestrictedWindow


@dataclass(frozen=True, kw_only=True)
class DeliveryConstraint:
    """Domain entity representing Project-level delivery rule."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    blackout_periods: list[BlackoutPeriod] = field(default_factory=list)
    restricted_windows: list[RestrictedWindow] = field(default_factory=list)
    timezone: str = "UTC"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        """Validate the entity's invariants after initialization."""
        # Validate timezone
        try:
            ZoneInfo(self.timezone)
        except ValueError as e:
            raise ValueError(f"Invalid timezone format: {self.timezone}") from e
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"Unknown or missing timezone: {self.timezone}") from e

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        blackout_periods: list[BlackoutPeriod] | None = None,
        restricted_windows: list[RestrictedWindow] | None = None,
        timezone: str = "UTC",
    ) -> DeliveryConstraint:
        """Create a new delivery constraint with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            blackout_periods=blackout_periods or [],
            restricted_windows=restricted_windows or [],
            timezone=timezone,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        blackout_periods: list[BlackoutPeriod],
        restricted_windows: list[RestrictedWindow],
        timezone: str,
        created_at: datetime,
        updated_at: datetime,
    ) -> DeliveryConstraint:
        """Rebuild an existing delivery constraint from persisted state."""
        return cls(
            id=id,
            project_id=project_id,
            blackout_periods=blackout_periods,
            restricted_windows=restricted_windows,
            timezone=timezone,
            created_at=created_at,
            updated_at=updated_at,
        )
