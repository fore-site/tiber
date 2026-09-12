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
