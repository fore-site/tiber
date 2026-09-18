"""Repository interfaces - DDD ports for data access.

These are abstract contracts the domain defines.
Concrete implementations live in infrastructure/persistence/repositories/.
Use cases in application/ depend only on these interfaces,
never on the SQLAlchemy implementations directly.

One repository per persisted domain entity, mirroring the domain model.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .entities import (
    APIKey,
    DeliveryAttempt,
    DeliveryConstraint,
    EngagementEvent,
    Notification,
    NotificationTopic,
    Project,
    Recipient,
    Template,
    User,
    WebhookEndpoint,
)
from .enums import DeliveryChannel, NotificationCategory
from .value_objects import TopicTitle


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

    async def get_by_slug(self, slug: str, user_id: UUID) -> Project | None:
        """Get a project by its slug within a user's scope.

        Scoped to ``user_id`` because the storage constraint is per-user
        uniqueness: the same slug can exist under different users, so an
        unscoped lookup would return an arbitrary row among them.
        """
        ...


class NotificationRepository(Protocol):
    """Contract for notification data access."""

    async def save(self, notification: Notification) -> Notification:
        """Save a notification to the repository."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> Notification | None:
        """Get a notification by its ID within a project's scope.

        Scoped like every other tenant-owned fetch: a mismatched project
        reads as a miss, so a caller bug surfaces as not-found instead of
        a cross-tenant read. Uniqueness of the UUID is not the point -
        the tenancy check being un-forgettable is.
        """
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

    async def get_by_address(
        self, project_id: UUID, channel: DeliveryChannel, address: str
    ) -> Recipient | None:
        """Get the recipient that owns a channel address within a project.

        The address-match rule: a raw-address send must attribute to the
        registered owner (opt-outs, history) before Tiber treats the
        address as unknown. Also the lookup behind registration's 409 on
        a contested address. The (project, channel, address) storage
        constraint is what makes this lookup unambiguous.
        """
        ...

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Recipient]:
        """List all recipients for a project with pagination."""
        ...


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


# Notification Topic
class NotificationTopicRepository(Protocol):
    """Contract for notification topic data access."""

    async def save(self, topic: NotificationTopic) -> NotificationTopic:
        """Save a notification topic to the repository."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> NotificationTopic | None:
        """Get a notification topic by its ID."""
        ...

    async def get_by_title(
        self, title: TopicTitle, project_id: UUID
    ) -> NotificationTopic | None:
        """Get a notification topic by its title."""
        ...

    async def list_by_category(
        self, project_id: UUID, category: NotificationCategory
    ) -> list[NotificationTopic]:
        """List all notification topics under a category."""
        ...

    async def list_by_project(self, project_id: UUID) -> list[NotificationTopic]:
        """List all notification topics for a project."""
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

    async def list_by_event(
        self, project_id: UUID, event_type: str
    ) -> list[WebhookEndpoint]:
        """List all webhook endpoints by event type for a project."""
        ...


# Delivery Policy
class DeliveryConstraintRepository(Protocol):
    """Contract for delivery constraint data access."""

    async def save(self, constraint: DeliveryConstraint) -> DeliveryConstraint:
        """Save a delivery constraint to the repository."""
        ...

    async def get_by_project(self, project_id: UUID) -> DeliveryConstraint | None:
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
