"""Unit tests for the stable Celery job payload contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from tiber.domain.entities import Notification
from tiber.domain.enums import DeliveryChannel, SendTimeBasis
from tiber.domain.value_objects import NotificationContent
from tiber.events.job_payload import (
    SCHEMA_VERSION,
    NotificationJobPayload,
    RetryState,
)


def make_notification(
    *,
    channel: DeliveryChannel = DeliveryChannel.EMAIL,
    scheduled_at: datetime | None = None,
) -> Notification:
    """Build a persisted-style notification for payload building."""
    return Notification(
        id=uuid4(),
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=channel,
        content=NotificationContent(
            subject="Hi" if channel is DeliveryChannel.EMAIL else None,
            body="Hello",
        ),
        scheduled_at=scheduled_at,
        send_time_basis=(
            SendTimeBasis.EXPLICIT if scheduled_at else SendTimeBasis.IMMEDIATE
        ),
    )


def test_from_entity_carries_stable_metadata():
    """Payload from an entity keeps identity, tracing, and scheduling fields."""
    n = make_notification(scheduled_at=datetime.now(UTC) + timedelta(hours=1))
    payload = NotificationJobPayload.from_entity(n)

    assert payload.schema_version == SCHEMA_VERSION
    assert payload.notification_id == n.id
    assert payload.project_id == n.project_id
    assert payload.recipient_id == n.recipient_id
    assert payload.correlation_id == n.correlation_id
    assert payload.channel == n.channel
    assert payload.scheduled_at == n.scheduled_at
    assert payload.send_time_basis == SendTimeBasis.EXPLICIT
    assert payload.retry == RetryState()


def test_payload_json_round_trips():
    """A JSON-serializable dict survives a serialization round-trip unchanged."""
    n = make_notification()
    payload = NotificationJobPayload.from_entity(n)

    restored = NotificationJobPayload.model_validate(payload.to_json_dict())

    assert restored == payload


def test_routing_key_is_channel_scoped():
    """Routing key scopes the job to its channel's delivery queue."""
    assert (
        NotificationJobPayload.from_entity(
            make_notification(channel=DeliveryChannel.EMAIL)
        ).routing_key
        == "notification.email"
    )
    assert (
        NotificationJobPayload.from_entity(
            make_notification(channel=DeliveryChannel.IN_APP)
        ).routing_key
        == "notification.in_app"
    )


def test_send_time_basis_immediate_by_default():
    """Without a schedule the payload is an immediate job."""
    payload = NotificationJobPayload.from_entity(make_notification())
    assert payload.send_time_basis == SendTimeBasis.IMMEDIATE
    assert payload.scheduled_at is None


def test_retry_state_is_bounded():
    """RetryState exposes next attempt and an exhaustion flag."""
    state = RetryState(attempt=0, max_attempts=4)
    assert not state.is_exhausted()

    for _ in range(4):
        state = state.next_attempt()
    assert state.attempt == 4
    assert state.is_exhausted()
