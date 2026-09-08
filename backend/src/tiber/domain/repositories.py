"""Repository interfaces - DDD ports for data access.

These are abstract contracts the domain defines.
Concrete implementations live in infrastructure/persistence/repositories/.
Use cases in application/ depend only on these interfaces,
never on the SQLAlchemy implementations directly.

One repository per persisted domain entity, mirroring the domain model.
Delivery Channel is an enum, not an entity, so it has no repository.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .entities import (
    APIKey,
    DeliveryAttempt,
    DeliveryPolicy,
    EngagementEvent,
    Notification,
    Project,
    Recipient,
    Template,
    User,
    WebhookEndpoint,
)


class UserRepository(Protocol):
    """Contract for user data access."""

    async def save(self, user: User) -> User:
        """Persist a user."""
        ...

    async def get_by_id(self, id: UUID) -> User | None:
        """Get a user by its ID."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Get a user by its email address."""
        ...


class ProjectRepository(Protocol):
    """Contract for project data access."""

    async def save(self, project: Project) -> Project:
        """Save a project to the repository."""
        ...

    async def get_by_id(self, id: UUID) -> Project | None:
        """Get a project by its ID."""
        ...

    async def get_by_slug(self, slug: str) -> Project | None:
        """Get a project by its slug."""
        ...


class NotificationRepository(Protocol):
    """Contract for notification data access."""

    async def save(self, notification: Notification) -> Notification:
        """Persist a notification.

        Implementations are responsible for ensuring persistence semantics
        appropriate for their storage backend (e.g concurrency control).
        """
        ...

    async def get_by_id(self, id: UUID) -> Notification | None:
        """Get a notification by its ID."""
        ...

    async def get_by_idempotency_key(
        self, project_id: UUID, key: str
    ) -> Notification | None:
        """Get a notification by its idempotency key."""
        ...

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Notification]:
        """List all notifications for a project with pagination."""
        ...


class APIKeyRepository(Protocol):
    """Contract for API key data access."""

    async def save(self, api_key: APIKey) -> APIKey:
        """Save an API key to the repository."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> APIKey | None:
        """Get an API key by its ID."""
        ...

    async def get_by_hash(self, key_hash: str) -> APIKey | None:
        """Get an API key by its hash."""
        ...

    async def revoke(self, id: UUID, project_id: UUID) -> None:
        """Revoke an API key."""
        ...

    async def list_by_project(self, project_id: UUID) -> list[APIKey]:
        """List all API keys for a project."""
        ...


# Template


class TemplateRepository(Protocol):
    """Contract for template data access."""

    async def save(self, template: Template) -> Template:
        """Save a template to the repository."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> Template | None:
        """Get a template by its ID."""
        ...

    async def get_by_slug(self, slug: str, project_id: UUID) -> Template | None:
        """Get a template by its slug."""
        ...

    async def list_by_project(self, project_id: UUID) -> list[Template]:
        """List all templates for a project."""
        ...


# Recipient


class RecipientRepository(Protocol):
    """Contract for recipient data access."""

    async def save(self, recipient: Recipient) -> Recipient:
        """Save a recipient to the repository."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> Recipient | None:
        """Get a recipient by its ID."""
        ...

    async def get_by_external_id(
        self, external_id: str, project_id: UUID
    ) -> Recipient | None:
        """Get a recipient by its external ID."""
        ...

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Recipient]:
        """List all recipients for a project with pagination."""
        ...


# Notification


# Delivery Attempt


class DeliveryAttemptRepository(Protocol):
    """Contract for delivery attempt data access."""

    async def save(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        """Save a delivery attempt to the repository."""
        ...

    async def list_by_notification(
        self, notification_id: UUID
    ) -> list[DeliveryAttempt]:
        """List all delivery attempts for a notification."""
        ...


# Webhook Endpoint


class WebhookEndpointRepository(Protocol):
    """Contract for webhook endpoint data access."""

    async def save(self, endpoint: WebhookEndpoint) -> WebhookEndpoint:
        """Save a webhook endpoint to the repository."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> WebhookEndpoint | None:
        """Get a webhook endpoint by its ID."""
        ...

    async def list_by_project(self, project_id: UUID) -> list[WebhookEndpoint]:
        """List all webhook endpoints for a project."""
        ...

    async def list_by_project_and_event(
        self, project_id: UUID, event_type: str
    ) -> list[WebhookEndpoint]:
        """List all webhook endpoints for a project and event type."""
        ...


# Delivery Policy


class DeliveryPolicyRepository(Protocol):
    """Contract for delivery policy data access."""

    async def save(self, policy: DeliveryPolicy) -> DeliveryPolicy:
        """Save a delivery policy to the repository."""
        ...

    async def get_by_project(self, project_id: UUID) -> DeliveryPolicy | None:
        """Get a delivery policy by its project ID."""
        ...


# Engagement Event


class EngagementEventRepository(Protocol):
    """Contract for engagement event data access."""

    async def save(self, event: EngagementEvent) -> EngagementEvent:
        """Save an engagement event to the repository."""
        ...

    async def list_by_notification(
        self, notification_id: UUID
    ) -> list[EngagementEvent]:
        """List all engagement events for a notification."""
        ...

    async def list_by_recipient(
        self, recipient_id: UUID, limit: int
    ) -> list[EngagementEvent]:
        """List all engagement events for a recipient."""
        ...
