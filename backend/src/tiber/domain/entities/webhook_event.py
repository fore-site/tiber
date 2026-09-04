from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class WebhookEvent:
    """Domain entity representing a record of each outbound webhook callback attempt."""

    id: UUID
