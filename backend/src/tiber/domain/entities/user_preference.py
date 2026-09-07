from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from ..enums import DeliveryChannel


@dataclass(frozen=True)
class UserPreference:
    """Domain entity representing delivery preference."""

    id: UUID
    recipient_id: UUID
    project_id: UUID
    preferred_channels: list[DeliveryChannel] = field(default_factory=list)
    opted_out_channels: list[DeliveryChannel] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
