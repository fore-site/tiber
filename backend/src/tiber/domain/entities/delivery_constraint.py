from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..value_objects import BlackoutPeriod, DeliveryWindow


@dataclass(frozen=True, kw_only=True)
class DeliveryConstraint:
    """Domain entity representing Project-level delivery rule."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    blackout_periods: list[BlackoutPeriod] = field(default_factory=list)
    delivery_windows: list[DeliveryWindow] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        blackout_periods: list[BlackoutPeriod] | None = None,
        delivery_windows: list[DeliveryWindow] | None = None,
    ) -> DeliveryConstraint:
        """Create a new delivery constraint with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            blackout_periods=blackout_periods or [],
            delivery_windows=delivery_windows or [],
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        blackout_periods: list[BlackoutPeriod],
        delivery_windows: list[DeliveryWindow],
        created_at: datetime,
        updated_at: datetime,
    ) -> DeliveryConstraint:
        """Rebuild an existing delivery constraint from persisted state."""
        return cls(
            id=id,
            project_id=project_id,
            blackout_periods=blackout_periods,
            delivery_windows=delivery_windows,
            created_at=created_at,
            updated_at=updated_at,
        )
