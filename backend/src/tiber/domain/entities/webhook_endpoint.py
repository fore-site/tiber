from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class WebhookEndpoint:
    """Domain entity representing client-registered outbound callback destinations."""

    id: UUID
