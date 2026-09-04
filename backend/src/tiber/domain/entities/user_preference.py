from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class UserPreference:
    """Domain entity representing delivery preference."""

    id: UUID
