from datetime import UTC, datetime, timedelta
from uuid import uuid4

from tiber.application.ports.outbox_relay import OutboxMessage
from tiber.application.services.outbox_relay import OutboxRelayService
from tiber.domain.entities import Notification
from tiber.domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    SendTimeBasis,
)
from tiber.domain.value_objects import NotificationContent


class _UnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None


class _Outbox:
    def __init__(self, messages):
        self.messages = list(messages)
        self.published = []
        self.failed = []

    async def claim_next(self, now):
        return self.messages.pop(0) if self.messages else None

    async def mark_published(self, message_id, published_at):
        self.published.append((message_id, published_at))

    async def mark_failed(self, message_id, *, failed_at, error, next_attempt_at):
        self.failed.append((message_id, failed_at, error, next_attempt_at))


class _Notifications:
    def __init__(self, notification):
        self.notification = notification

    async def get_by_id(self, notification_id, project_id):
        if (
            notification_id == self.notification.id
            and project_id == self.notification.project_id
        ):
            return self.notification
        return None


class _Publisher:
    def __init__(self, *, failure=None):
        self.calls = []
        self.failure = failure

    async def publish_intake(self, intake_id, transaction_id=None):
        self.calls.append(("intake", intake_id))
        if self.failure:
            raise self.failure

    async def publish_notification(self, notification):
        self.calls.append(("dispatch", notification.id))
        if self.failure:
            raise self.failure


def _notification():
    return Notification.create(
        project_id=uuid4(),
        recipient_id=uuid4(),
        transaction_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.INFORMATIONAL,
        content=NotificationContent(title="Subject", plain_text_body="Message"),
        send_time_basis=SendTimeBasis.IMMEDIATE,
    )


async def test_relay_publishes_intakes_and_dispatches():
    """Relay dispatches both message kinds and marks each committed."""
    notification = _notification()
    intake_id = uuid4()
    outbox = _Outbox(
        [
            OutboxMessage(
                id=1,
                kind="intake",
                aggregate_id=intake_id,
                payload={"intake_id": str(intake_id)},
                attempts=0,
            ),
            OutboxMessage(
                id=2,
                kind="dispatch",
                aggregate_id=notification.id,
                payload={"project_id": str(notification.project_id)},
                attempts=0,
            ),
        ]
    )
    publisher = _Publisher()
    service = OutboxRelayService(
        unit_of_work=_UnitOfWork(),
        outbox_repository=outbox,
        notification_repository=_Notifications(notification),
        publisher=publisher,
        clock=lambda: datetime(2026, 11, 5, tzinfo=UTC),
    )

    result = await service.relay_available()

    assert result == 2
    assert publisher.calls == [
        ("intake", intake_id),
        ("dispatch", notification.id),
    ]
    assert [row[0] for row in outbox.published] == [1, 2]


async def test_relay_records_bounded_retry_after_publish_error():
    """Relay stores the next exponential retry time after a broker error."""
    intake_id = uuid4()
    now = datetime(2026, 11, 5, tzinfo=UTC)
    outbox = _Outbox(
        [
            OutboxMessage(
                id=9,
                kind="intake",
                aggregate_id=intake_id,
                payload={"intake_id": str(intake_id)},
                attempts=1,
            )
        ]
    )
    service = OutboxRelayService(
        unit_of_work=_UnitOfWork(),
        outbox_repository=outbox,
        notification_repository=_Notifications(_notification()),
        publisher=_Publisher(failure=RuntimeError("broker unavailable")),
        retry_base_seconds=2,
        clock=lambda: now,
    )

    result = await service.relay_available()

    assert result == 0
    assert outbox.failed == [
        (9, now, "RuntimeError: broker unavailable", now + timedelta(seconds=4))
    ]


async def test_relay_dead_letters_after_maximum_attempts():
    """Relay dead-letters rows that exhaust their publication attempt budget."""
    intake_id = uuid4()
    now = datetime(2026, 11, 5, tzinfo=UTC)
    outbox = _Outbox(
        [
            OutboxMessage(
                id=10,
                kind="intake",
                aggregate_id=intake_id,
                payload={"intake_id": str(intake_id)},
                attempts=2,
            )
        ]
    )
    service = OutboxRelayService(
        unit_of_work=_UnitOfWork(),
        outbox_repository=outbox,
        notification_repository=_Notifications(_notification()),
        publisher=_Publisher(failure=RuntimeError("broker unavailable")),
        max_attempts=3,
        clock=lambda: now,
    )

    result = await service.relay_available()

    assert result == 0
    assert outbox.failed[0][3] is None
