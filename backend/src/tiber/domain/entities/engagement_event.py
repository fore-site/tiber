from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class EngagementEvent:
    """Domain entity representing recipient interaction reported by delivery providers."""

    id: UUID
