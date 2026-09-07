from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from ..enums import WebhookEventType


@dataclass(frozen=True)
class WebhookEndpoint:
    """Domain entity representing client-registered outbound callback destinations."""

    id: UUID
    project_id: UUID
    url: str
    events: list[WebhookEventType]
    encrypted_signing_secret: str
    secret_prefix: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
