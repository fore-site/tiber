"""Pins for client-reported engagement events.

The client is the source of truth only for push and in-app interactions, and
only if a retried report cannot duplicate a training signal. These tests cover
the trust boundary, the channel split, idempotency, and page cursors.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from tiber.api.schemas.engagement_event import EngagementEventReportRequest
from tiber.application.services.engagement_event import EngagementEventService
from tiber.domain.entities import EngagementEvent
from tiber.domain.enums import DeliveryChannel, EngagementEventType
from tiber.domain.exceptions import (
    IdempotencyKeyConflictError,
    InvalidEntityAttributeError,
)

OCCURRED_AT = datetime(2026, 11, 12, 9, 14, 3, tzinfo=UTC)


class _UnitOfWork:
    """No-op transaction boundary: the fakes commit instantly."""

    async def __aenter__(self) -> _UnitOfWork:
        """Enter the transaction."""
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        """Leave the transaction without suppressing anything."""
        return False


class _Notifications:
    """Return one notification, project-scoped like the real repository."""

    def __init__(self, notification: SimpleNamespace) -> None:
        """Store the notification under test."""
        self._notification = notification

    async def get_by_id(
        self, notification_id: UUID, project_id: UUID
    ) -> SimpleNamespace | None:
        """Return the notification only for its own id and project."""
        notification = self._notification
        if notification.id == notification_id and notification.project_id == project_id:
            return notification
        return None


class _Events:
    """Append-only in-memory store with the partial unique index and cursor."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: list[EngagementEvent] = []

    async def save(self, event: EngagementEvent) -> EngagementEvent:
        """Store an event unconditionally."""
        self.rows.append(event)
        return event

    async def insert_if_absent(self, event: EngagementEvent) -> bool:
        """Mimic ON CONFLICT DO NOTHING on the project/key pair."""
        if (
            event.idempotency_key is not None
            and await self.get_by_idempotency_key(
                event.project_id, event.idempotency_key
            )
            is not None
        ):
            return False
        self.rows.append(event)
        return True

    async def get_by_idempotency_key(
        self, project_id: UUID, idempotency_key: str
    ) -> EngagementEvent | None:
        """Find the event stored under a project-scoped key."""
        return next(
            (
                event
                for event in self.rows
                if event.project_id == project_id
                and event.idempotency_key == idempotency_key
            ),
            None,
        )

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
        **_filters: object,
    ) -> list[EngagementEvent]:
        """Return rows newest first, applying the same keyset as the database."""
        rows = sorted(
            (event for event in self.rows if event.project_id == project_id),
            key=lambda event: (event.occurred_at, event.id),
            reverse=True,
        )
        if cursor is not None:
            occurred_at, event_id = cursor
            rows = [
                event
                for event in rows
                if (event.occurred_at, event.id) < (occurred_at, event_id)
            ]
        return rows[:limit]


def _notification(channel: DeliveryChannel) -> SimpleNamespace:
    """Build the fields the service reads from a notification."""
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        recipient_id=uuid4(),
        channel=channel,
    )


def _service(
    notification: SimpleNamespace,
) -> tuple[EngagementEventService, _Events]:
    """Wire the service against the in-memory fakes."""
    events = _Events()
    service = EngagementEventService(
        unit_of_work=_UnitOfWork(),
        event_repository=events,
        notification_repository=_Notifications(notification),
    )
    return service, events


def _event(notification: SimpleNamespace, occurred_at: datetime) -> EngagementEvent:
    """Build a stored event without going through the write path."""
    return EngagementEvent.create(
        notification_id=notification.id,
        project_id=notification.project_id,
        recipient_id=notification.recipient_id,
        event_type=EngagementEventType.OPEN,
        channel=DeliveryChannel.PUSH,
        provider="client",
        occurred_at=occurred_at,
    )


def _report(
    service: EngagementEventService,
    notification: SimpleNamespace,
    *,
    event_type: EngagementEventType = EngagementEventType.CLICK,
    idempotency_key: str = "report-1",
    metadata: dict | None = None,
):
    """Call ``record`` with the test clock and payload."""
    return asyncio.run(
        service.record(
            project_id=notification.project_id,
            notification_id=notification.id,
            event_type=event_type,
            occurred_at=OCCURRED_AT,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
    )


def test_push_report_derives_recipient_and_stores_key():
    """A push report is stored with the notification's recipient and the key."""
    notification = _notification(DeliveryChannel.PUSH)
    service, events = _service(notification)

    recorded = _report(service, notification)

    assert recorded.created
    assert len(events.rows) == 1
    stored = events.rows[0]
    assert stored.recipient_id == notification.recipient_id
    assert stored.channel is DeliveryChannel.PUSH
    assert stored.provider == "client"
    assert stored.idempotency_key == "report-1"


def test_in_app_report_is_allowed():
    """In-app taps have no provider callback, so the client may report them."""
    notification = _notification(DeliveryChannel.IN_APP)
    service, events = _service(notification)

    recorded = _report(service, notification)

    assert recorded.created
    assert events.rows[0].channel is DeliveryChannel.IN_APP


@pytest.mark.parametrize("channel", [DeliveryChannel.EMAIL, DeliveryChannel.SMS])
def test_provider_reported_channels_are_rejected(channel: DeliveryChannel):
    """Email and SMS engagement must arrive from the provider, not the client."""
    notification = _notification(channel)
    service, events = _service(notification)

    with pytest.raises(InvalidEntityAttributeError, match="provider"):
        _report(service, notification)

    assert events.rows == []


def test_blank_key_is_rejected():
    """Whitespace passes the header's min_length but cannot identify a report."""
    notification = _notification(DeliveryChannel.PUSH)
    service, events = _service(notification)

    with pytest.raises(InvalidEntityAttributeError, match="non-empty"):
        _report(service, notification, idempotency_key="   ")

    assert events.rows == []


def test_same_key_and_payload_replays_without_a_second_row():
    """A retried report returns the original row and creates nothing."""
    notification = _notification(DeliveryChannel.PUSH)
    service, events = _service(notification)

    first = _report(service, notification, metadata={"deep_link": "tiber://x"})
    second = _report(service, notification, metadata={"deep_link": "tiber://x"})

    assert first.created
    assert not second.created
    assert second.event.id == first.event.id
    assert len(events.rows) == 1


def test_same_key_with_different_payload_conflicts():
    """Reusing a key for a different fact is a client bug, not a replay."""
    notification = _notification(DeliveryChannel.PUSH)
    service, _ = _service(notification)

    _report(service, notification, event_type=EngagementEventType.OPEN)

    with pytest.raises(IdempotencyKeyConflictError):
        _report(service, notification, event_type=EngagementEventType.CLICK)


def test_list_pages_with_an_opaque_cursor():
    """Two pages cover the rows exactly once, newest first."""
    notification = _notification(DeliveryChannel.PUSH)
    service, events = _service(notification)
    for minute in range(3):
        events.rows.append(
            _event(notification, OCCURRED_AT + timedelta(minutes=minute))
        )

    first = asyncio.run(service.list(notification.project_id, limit=2))
    second = asyncio.run(
        service.list(notification.project_id, limit=2, cursor=first.next_cursor)
    )

    assert len(first.items) == 2
    assert first.next_cursor is not None
    assert len(second.items) == 1
    assert second.next_cursor is None
    assert {event.id for event in first.items}.isdisjoint(
        {event.id for event in second.items}
    )
    assert first.items[0].occurred_at > first.items[1].occurred_at


def test_naive_occurred_at_is_rejected():
    """A timezone-naive timestamp cannot be placed on the engagement timeline."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        EngagementEventReportRequest(
            event_type=EngagementEventType.OPEN,
            occurred_at=datetime(2026, 11, 12, 9, 14, 3),
        )


def test_bounce_is_not_client_reportable():
    """Deliverability facts are provider-only; a client cannot claim one."""
    with pytest.raises(ValidationError, match="provider"):
        EngagementEventReportRequest(
            event_type=EngagementEventType.BOUNCE,
            occurred_at=OCCURRED_AT,
        )
