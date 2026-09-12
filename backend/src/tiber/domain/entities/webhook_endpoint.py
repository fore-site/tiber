from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import WebhookEventType


@dataclass(frozen=True, kw_only=True)
class WebhookEndpoint:
    """Domain entity representing client-registered outbound callback destinations."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    url: str
    events: list[WebhookEventType]
    encrypted_signing_secret: str
    secret_prefix: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
