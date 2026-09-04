from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Provider:
    """Domain entity representing a record of configured external delivery services and health state."""

    id: UUID
