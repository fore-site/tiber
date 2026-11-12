"""Recording and reading engagement events.

Events are written once and never mutated. Client-reported events require an
``Idempotency-Key``: the same key with the same payload replays the original
row, while a different payload raises ``IdempotencyKeyConflictError``. Provider
ingestion dedupes on the provider's event id instead and is a separate path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import EngagementEvent, Notification
from tiber.domain.enums import DeliveryChannel, EngagementEventType
from tiber.domain.exceptions import (
    ConflictError,
    EntityNotFoundError,
    IdempotencyKeyConflictError,
    InvalidEntityAttributeError,
)
from tiber.domain.repositories import (
    EngagementEventRepository,
    NotificationRepository,
)

_CLIENT_PROVIDER = "client"

# The client is the authoritative observer only where no delivery provider
# reports engagement to Tiber: push (FCM/APNs have no per-message webhooks) and
# in-app (the app renders the message itself). Email and SMS opens/clicks arrive
# from the provider and must not be self-reported.
_CLIENT_REPORTABLE_CHANNELS = frozenset({DeliveryChannel.PUSH, DeliveryChannel.IN_APP})


@dataclass(frozen=True)
class RecordedEngagementEvent:
    """Outcome of a report: the event plus whether this call created it."""

    event: EngagementEvent
    created: bool


class EngagementEventService:
    """Project-scoped recording and querying of engagement events."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        event_repository: EngagementEventRepository,
        notification_repository: NotificationRepository,
    ) -> None:
        """Initialize the service with its transaction boundary and repositories."""
        self._unit_of_work = unit_of_work
        self._events = event_repository
        self._notifications = notification_repository

    async def record(
        self,
        *,
        project_id: UUID,
        notification_id: UUID,
        event_type: EngagementEventType,
        occurred_at: datetime,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> RecordedEngagementEvent:
        """Record a client-reported event for one of its notifications.

        The notification lookup is what makes the event trustworthy: recipient
        and channel are taken from the stored notification, not from the
        request, so a client cannot attribute an event to another recipient.

        Only push and in-app notifications accept client reports; email and SMS
        engagement comes from the provider. The key is required: a retry with
        the same payload returns the original row (``created=False``); reusing
        the key for a different payload raises.
        """
        key = idempotency_key.strip()
        if not key:
            raise InvalidEntityAttributeError(
                "`Idempotency-Key` must be a non-empty string"
            )

        notification = await self._notifications.get_by_id(notification_id, project_id)
        if notification is None:
            raise EntityNotFoundError(Notification, str(notification_id))

        if notification.channel not in _CLIENT_REPORTABLE_CHANNELS:
            raise InvalidEntityAttributeError(
                f"Engagement events for '{notification.channel.value}' "
                "notifications are reported by the delivery provider; clients "
                "may report only 'push' and 'in_app' events."
            )

        existing = await self._events.get_by_idempotency_key(project_id, key)
        if existing is not None:
            return self._replay(
                existing,
                notification_id=notification_id,
                event_type=event_type,
                occurred_at=occurred_at,
                metadata=metadata,
            )

        event = EngagementEvent.create(
            notification_id=notification.id,
            project_id=project_id,
            recipient_id=notification.recipient_id,
            event_type=event_type,
            channel=notification.channel,
            provider=_CLIENT_PROVIDER,
            idempotency_key=key,
            occurred_at=occurred_at,
            metadata=metadata,
        )

        async with self._unit_of_work:
            inserted = await self._events.insert_if_absent(event)

        if inserted:
            return RecordedEngagementEvent(event=event, created=True)

        # Lost a race with an identical report: read the row that won.
        existing = await self._events.get_by_idempotency_key(project_id, key)
        if existing is None:
            raise ConflictError(
                "Engagement event idempotency key conflict could not be resolved."
            )
        return self._replay(
            existing,
            notification_id=notification_id,
            event_type=event_type,
            occurred_at=occurred_at,
            metadata=metadata,
        )

    @staticmethod
    def _replay(
        existing: EngagementEvent,
        *,
        notification_id: UUID,
        event_type: EngagementEventType,
        occurred_at: datetime,
        metadata: dict | None,
    ) -> RecordedEngagementEvent:
        """Return the stored event when the retried payload matches it exactly."""
        if (
            existing.notification_id != notification_id
            or existing.event_type != event_type
            or existing.occurred_at != occurred_at
            or existing.metadata != metadata
        ):
            raise IdempotencyKeyConflictError()
        return RecordedEngagementEvent(event=existing, created=False)

    async def get(self, project_id: UUID, event_id: UUID) -> EngagementEvent:
        """Return one event, scoped to the project."""
        event = await self._events.get_by_id(event_id, project_id)
        if event is None:
            raise EntityNotFoundError(EngagementEvent, str(event_id))
        return event

    async def list(
        self,
        project_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        event_type: EngagementEventType | None = None,
        recipient_id: UUID | None = None,
        notification_id: UUID | None = None,
        channel: DeliveryChannel | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
    ) -> list[EngagementEvent]:
        """List a project's events, newest first, with optional filters."""
        return await self._events.list_by_project(
            project_id,
            limit,
            offset,
            event_type=event_type,
            recipient_id=recipient_id,
            notification_id=notification_id,
            channel=channel,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
        )
