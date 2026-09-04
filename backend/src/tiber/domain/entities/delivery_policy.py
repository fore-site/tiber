from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DeliveryPolicy:
    """Domain entity representing Project-level delivery rule."""

    id: UUID
