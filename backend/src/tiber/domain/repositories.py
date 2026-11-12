"""Repository interfaces - DDD ports for data access.

These are abstract contracts the domain defines.

One repository per persisted domain entity, mirroring the domain model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .entities import (
    Account,
    APIKey,
    BrandProfile,
    DeliveryAttempt,
    DeliveryConstraint,
    EngagementEvent,
    Notification,
    NotificationIntake,
    NotificationTopic,
    Project,
    Recipient,
    Template,
    WebhookEndpoint,
)
from .enums import (
    DeliveryChannel,
    EngagementEventType,
    NotificationCategory,
    NotificationStatus,
    WebhookEventType,
)


class AccountRepository(Protocol):
    """Contract for account data access.

    Accounts are the id-only domain representation of platform accounts:
    ownership roots, not authentication state.
    """

    async def save(self, account: Account) -> Account:
        """Persist an account."""
        ...

    async def get_by_id(self, id: UUID) -> Account | None:
        """Get an account by its ID."""
        ...


class ProjectRepository(Protocol):
    """Contract for project data access."""

    async def save(self, project: Project) -> Project:
        """Save a project to the repository."""
        ...

    async def get_by_id(self, id: UUID) -> Project | None:
        """Get a project by its ID."""
        ...

    async def get_by_id_for_update(self, id: UUID) -> Project | None:
        """Load and lock a project row within the current transaction."""
        ...

    async def get_by_slug(self, slug: str, account_id: UUID) -> Project | None:
        """Get a project by its slug within an account's scope.

        Scoped to ``account_id`` because the storage constraint is
        per-account uniqueness: the same slug can exist under different
        accounts, so an unscoped lookup would return an arbitrary row among
        them.
        """
        ...

    async def list_by_account(
        self,
        account_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[Project]:
        """List a page of projects owned by an account, newest first."""
        ...

    async def purge(self, project_id: UUID) -> bool:
        """Permanently delete a project and its owned data; False if absent."""
        ...

    async def purge_expired(self, deleted_before: datetime, limit: int) -> int:
        """Permanently remove deleted projects older than the cutoff."""
        ...


class NotificationRepository(Protocol):
    """Contract for notification data access."""

    async def save(self, notification: Notification) -> Notification:
        """Save a notification to the repository."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> Notification | None:
        """Get a notification by its ID within a project's scope."""
        ...

    async def cancel_pending(self, notification: Notification) -> bool:
        """Atomically cancel a pending notification; return whether it was updated."""
        ...

    async def claim_for_delivery(
        self,
        notification: Notification,
        *,
        expected_status: NotificationStatus,
        stale_before: datetime | None = None,
    ) -> bool:
        """Atomically transition a deliverable or stale processing row to PROCESSING."""
        ...

    async def get_by_idempotency_key(
        self, project_id: UUID, key: str
    ) -> Notification | None:
        """Get a notification by its idempotency key."""
        ...

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[Notification]:
        """List a page of a project's notifications, newest first.

        ``cursor`` is the ``(created_at, id)`` of the last notification already
        returned; the id makes the ordering total for equal timestamps.
        """
        ...

    async def list_by_transaction_id(
        self, transaction_id: UUID, project_id: UUID
    ) -> list[Notification]:
        """All notifications created by one request, oldest first."""
        ...

    async def reassign_recipient(
        self,
        *,
        project_id: UUID,
        from_recipient_id: UUID,
        to_recipient_id: UUID,
    ) -> int:
        """UPDATE notifications SET recipient_id = :to WHERE project_id = :p AND recipient_id = :from.

        Returns rows moved.
        """
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

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[APIKey]:
        """List a page of a project's API keys, newest first."""
        ...

    async def count_by_project(self, project_id: UUID) -> int:
        """Count all API keys owned by a project."""
        ...

    async def list_by_account(self, account_id: UUID) -> list[APIKey]:
        """List API keys belonging to projects owned by an account."""
        ...


# Template
class TemplateRepository(Protocol):
    """Contract for template data access."""

    async def save(self, template: Template) -> Template:
        """Save a template to the repository."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> Template | None:
        """Get a template by its ID within a project's scope."""
        ...

    async def get_by_slug(self, slug: str, project_id: UUID) -> Template | None:
        """Get a template by its slug within a project's scope.

        The accept path resolves the client's slug once and stores the
        template's id, so a later rename cannot retarget accepted work.
        """
        ...

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
        channel: DeliveryChannel | None = None,
    ) -> list[Template]:
        """List a page of a project's templates, newest first."""
        ...

    async def delete(self, template: Template) -> None:
        """Delete a project-scoped template."""
        ...


class BrandProfileRepository(Protocol):
    """Contract for project-scoped brand profile data access."""

    async def save(self, profile: BrandProfile) -> BrandProfile:
        """Persist a brand profile."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> BrandProfile | None:
        """Load a brand profile within its project's scope."""
        ...

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[BrandProfile]:
        """List a page of brand profiles within a project, newest first."""
        ...

    async def delete(self, profile: BrandProfile) -> None:
        """Delete a project-scoped brand profile."""
        ...


# Recipient
class RecipientRepository(Protocol):
    """Contract for recipient data access."""

    async def add(self, recipient: Recipient) -> Recipient:
        """Insert a recipient into the repository."""
        ...

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

    async def find_by_addresses(
        self, project_id: UUID, addresses: Mapping[DeliveryChannel, str]
    ) -> list[Recipient]:
        """Return distinct, NON-deleted recipients holding any of the ``(channel, address)`` pairs."""
        ...

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
        external_id: str | None = None,
    ) -> list[Recipient]:
        """List a page of a project's recipients, newest first.

        ``external_id`` narrows the page to one exact identifier.
        """
        ...

    async def delete(self, recipient: Recipient) -> None:
        """Permanently delete a recipient; conflicts when history references it."""
        ...

    async def get_many_for_update(
        self, project_id: UUID, ids: Sequence[UUID]
    ) -> list[Recipient]:
        """SELECT ... WHERE project_id = :p AND id = ANY(:ids) ORDER BY id FOR UPDATE.

        Used by the recipient merge service;
        callers pass ``ids`` pre-sorted so concurrent merges lock in the same order.
        """
        ...


# Delivery Attempt
class DeliveryAttemptRepository(Protocol):
    """Contract for delivery attempt data access."""

    async def save(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        """Save a delivery attempt to the repository."""
        ...

    async def get_by_id(
        self, id: UUID, notification_id: UUID
    ) -> DeliveryAttempt | None:
        """Get an attempt by id, scoped to its notification."""
        ...

    async def next_attempt_number(self, notification_id: UUID) -> int:
        """Return the next 1-based attempt number for a notification.

        A read-then-insert race between two workers is possible in principle;
        the ``(notification_id, attempt_number)`` unique constraint rejects the
        loser instead of silently overwriting history. Attempts are only
        recorded after a notification is claimed for delivery, so the race is
        not expected in practice.
        """
        ...

    async def list_by_notification(
        self,
        notification_id: UUID,
        limit: int,
        *,
        cursor: int | None = None,
    ) -> list[DeliveryAttempt]:
        """List a page of attempts for a notification, oldest first.

        ``cursor`` is the last ``attempt_number`` already returned; None starts
        at the first attempt. Keyset selection keeps the page stable even if
        attempts are appended while a client walks the history.
        """
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

    async def get_by_slug(
        self, slug: str, project_id: UUID
    ) -> NotificationTopic | None:
        """Get a notification topic by its slug."""
        ...

    async def get_by_title(
        self, title: str, project_id: UUID
    ) -> NotificationTopic | None:
        """Get a notification topic by its title."""
        ...

    async def list_by_category(
        self, project_id: UUID, category: NotificationCategory, limit: int, offset: int
    ) -> list[NotificationTopic]:
        """List all notification topics under a category."""
        ...

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[NotificationTopic]:
        """List a page of a project's notification topics, newest first."""
        ...

    async def delete(self, topic: NotificationTopic) -> None:
        """Permanently delete a project-scoped topic."""
        ...


# Webhook Endpoint
class WebhookEndpointRepository(Protocol):
    """Contract for webhook endpoint data access."""

    async def save(self, endpoint: WebhookEndpoint) -> WebhookEndpoint:
        """Insert or update a webhook endpoint."""
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> WebhookEndpoint | None:
        """Get a webhook endpoint by its ID within a project's scope."""
        ...

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[WebhookEndpoint]:
        """List a page of a project's endpoints, newest first.

        ``cursor`` is the ``(created_at, id)`` of the last endpoint already
        returned; the id makes the ordering total for equal timestamps.
        """
        ...

    async def list_by_event(
        self,
        project_id: UUID,
        event_type: WebhookEventType,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[WebhookEndpoint]:
        """List a page of the project's endpoints subscribed to one event type."""
        ...

    async def delete(self, id: UUID, project_id: UUID) -> bool:
        """Delete an endpoint; False when it does not exist in the project."""
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

    async def load_constraint(self, project_id: UUID) -> DeliveryConstraint | None:
        """Load the constraint for policy evaluation, None when absent.

        Deliberately distinct from ``get_by_project``: policy evaluation is
        a read-for-decision, not a read-for-display. A missing configuration
        is a normal state (permissive default: no constraints configured),
        not an error, so the lookup returns None instead of raising.
        """
        ...


# Engagement Event
class EngagementEventRepository(Protocol):
    """Contract for engagement event data access."""

    async def save(self, event: EngagementEvent) -> EngagementEvent:
        """Save an engagement event to the repository."""
        ...

    async def get_by_idempotency_key(
        self, project_id: UUID, idempotency_key: str
    ) -> EngagementEvent | None:
        """Get a client-reported event by its project-scoped idempotency key."""
        ...

    async def insert_if_absent(self, event: EngagementEvent) -> bool:
        """Insert an event unless ``(project_id, idempotency_key)`` is taken.

        Returns ``True`` when the row was inserted and ``False`` when the key
        already exists. Uses ``ON CONFLICT DO NOTHING`` so a lost race leaves
        the surrounding transaction usable and the caller can re-read the winner.
        """
        ...

    async def get_by_id(self, id: UUID, project_id: UUID) -> EngagementEvent | None:
        """Get an event by id within a project's scope."""
        ...

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
        event_type: EngagementEventType | None = None,
        recipient_id: UUID | None = None,
        notification_id: UUID | None = None,
        channel: DeliveryChannel | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
    ) -> list[EngagementEvent]:
        """List a page of a project's events, newest first, with filters.

        ``cursor`` is the ``(occurred_at, id)`` of the last event already
        returned. The id breaks ties between events sharing a timestamp, so
        the ordering is total and pages cannot overlap.
        """
        ...

    async def list_by_notification(
        self,
        notification_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[EngagementEvent]:
        """List a page of engagement events for a notification, newest first."""
        ...

    async def list_by_recipient(
        self,
        recipient_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[EngagementEvent]:
        """List a page of engagement events for a recipient, newest first."""
        ...


class NotificationIntakeRepository(Protocol):
    """Contract for notification intake data access."""

    async def add(self, intake: NotificationIntake) -> None:
        """Insert NotificationIntake.

        Raises ``ConflictError`` when ``(project_id, idempotency_key)`` is taken.
        Use a savepoint or ON CONFLICT DO NOTHING so the surrounding transaction stays usable and
        the caller can re-read the winner.
        """
        ...

    async def get_by_transaction_id(
        self, transaction_id: UUID, project_id: UUID
    ) -> NotificationIntake | None:
        """Get a notification made from a request."""
        ...

    async def get_by_idempotency_key(
        self, project_id: UUID, idempotency_key: str
    ) -> NotificationIntake | None:
        """Get notification by idempotency key."""
        ...

    async def get_for_update(self, intake_id: UUID) -> NotificationIntake | None:
        """SELECT ... FOR UPDATE SKIP LOCKED.

        Returns None if the row is missing or locked by another worker.
        """

    async def save(self, intake: NotificationIntake) -> None:
        """Save NotificationIntake."""
        ...
