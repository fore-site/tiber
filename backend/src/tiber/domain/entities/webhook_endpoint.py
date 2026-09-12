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

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        url: str,
        events: list[WebhookEventType],
        encrypted_signing_secret: str,
        secret_prefix: str,
    ) -> WebhookEndpoint:
        """Create a new webhook endpoint with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            url=url,
            events=events,
            encrypted_signing_secret=encrypted_signing_secret,
            secret_prefix=secret_prefix,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        url: str,
        events: list[WebhookEventType],
        encrypted_signing_secret: str,
        secret_prefix: str,
        created_at: datetime,
        updated_at: datetime,
    ) -> WebhookEndpoint:
        """Rebuild an existing webhook endpoint from persisted state."""
        return cls(
            id=id,
            project_id=project_id,
            url=url,
            events=events,
            encrypted_signing_secret=encrypted_signing_secret,
            secret_prefix=secret_prefix,
            created_at=created_at,
            updated_at=updated_at,
        )
