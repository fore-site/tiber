from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from ..value_objects import BlackoutPeriod


@dataclass(frozen=True)
class DeliveryPolicy:
    """Domain entity representing Project-level delivery rule."""

    id: UUID
    project_id: UUID
    blackout_periods: list[BlackoutPeriod] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
