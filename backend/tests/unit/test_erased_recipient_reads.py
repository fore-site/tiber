"""Reads that mix live and erased recipients.

After the deletion grace period the recipient row is purged and the history
rows lose only their pointer. These tests pin the read side of that rule: an
erased recipient renders as null, never as an error, and never as a crash from
mixing ``None`` into a set of UUIDs.

They use in-memory repositories so the assertions are about the service's
decisions, not about SQL.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from tiber.api.schemas.engagement_event import EngagementEventResponse
from tiber.api.schemas.intake import IntakeStatusResponse
from tiber.application.services.notification_query import NotificationQueryService
from tiber.domain.entities import EngagementEvent, Notification, Recipient
from tiber.domain.entities.notification_intake import NotificationIntake
from tiber.domain.enums import (
    DeliveryChannel,
    EngagementEventType,
    NotificationCategory,
    SendTimeBasis,
)
from tiber.domain.value_objects import NotificationContent
from tiber.domain.value_objects.intake import DecisionConstraints, IntakePayload


class _NotificationRepository:
    """Stands in for the notification read port."""

    def __init__(self, notifications: list[Notification]) -> None:
        self._notifications = notifications

    async def get_by_id(
        self, notification_id: UUID, project_id: UUID
    ) -> Notification | None:
        for notification in self._notifications:
            if (
                notification.id == notification_id
                and notification.project_id == project_id
            ):
                return notification
        return None

    async def list_by_project(self, project_id: UUID, limit: int, **_: object):
        matching = [n for n in self._notifications if n.project_id == project_id]
        return matching[:limit]

    async def list_by_transaction_id(
        self, transaction_id: UUID, project_id: UUID
    ) -> list[Notification]:
        return [
            n
            for n in self._notifications
            if n.transaction_id == transaction_id and n.project_id == project_id
        ]


class _IntakeRepository:
    """Stands in for the intake read port."""

    def __init__(self, intake: NotificationIntake | None) -> None:
        self._intake = intake

    async def get_by_transaction_id(
        self, transaction_id: UUID, project_id: UUID
    ) -> NotificationIntake | None:
        if self._intake is None:
            return None
        matches = (
            self._intake.transaction_id == transaction_id
            and self._intake.project_id == project_id
        )
        return self._intake if matches else None


class _RecipientRepository:
    """Records the ids it is asked for, so a null lookup is visible."""

    def __init__(self, recipients: list[Recipient]) -> None:
        self._recipients = recipients
        self.requested: list[UUID | None] = []

    async def get_by_id(self, recipient_id: UUID, project_id: UUID) -> Recipient | None:
        self.requested.append(recipient_id)
        for recipient in self._recipients:
            if recipient.id == recipient_id and recipient.project_id == project_id:
                return recipient
        return None

    async def get_many_by_ids(
        self, project_id: UUID, ids: list[UUID]
    ) -> list[Recipient]:
        self.requested.extend(ids)
        wanted = set(ids)
        return [
            r for r in self._recipients if r.project_id == project_id and r.id in wanted
        ]


def _notification(
    *, project_id: UUID, recipient_id: UUID | None, transaction_id: UUID | None = None
) -> Notification:
    """Build a notification for a recipient that may already be erased."""
    created = Notification.create(
        project_id=project_id,
        recipient_id=recipient_id or uuid4(),
        transaction_id=transaction_id or uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.INFORMATIONAL,
        content=NotificationContent(title="Hi", plain_text_body="Hi"),
        send_time_basis=SendTimeBasis.IMMEDIATE,
    )
    # Erasure only ever happens to a stored row, so model it that way: the
    # entity is reconstituted from the database with a null pointer.
    return replace(created, recipient_id=recipient_id)


def _intake(
    *, project_id: UUID, recipient_id: UUID | None, channel_mode: str = "client"
) -> NotificationIntake:
    """Build an intake whose recipient may already be erased."""
    created = NotificationIntake.create(
        project_id=project_id,
        recipient_id=recipient_id or uuid4(),
        payload=IntakePayload(
            channels=(DeliveryChannel.EMAIL,),
            content=NotificationContent(title="Hi", plain_text_body="Hi"),
        ),
        constraints=DecisionConstraints(
            allowed_categories=frozenset({NotificationCategory.INFORMATIONAL}),
            default_category=NotificationCategory.INFORMATIONAL,
            channel_mode=channel_mode,
        ),
        request_fingerprint="fingerprint",
    )
    return replace(created, recipient_id=recipient_id)


def _service(
    notifications: list[Notification],
    recipients: list[Recipient],
    intake: NotificationIntake | None = None,
) -> tuple[NotificationQueryService, _RecipientRepository]:
    recipient_repository = _RecipientRepository(recipients)
    return (
        NotificationQueryService(
            notification_repository=_NotificationRepository(notifications),
            intake_repository=_IntakeRepository(intake),
            recipient_repository=recipient_repository,
        ),
        recipient_repository,
    )


@pytest.mark.asyncio
async def test_page_renders_erased_recipients_as_null() -> None:
    """A page holding an erased recipient must not crash on the batch lookup."""
    project_id = uuid4()
    live = Recipient.create(
        project_id=project_id,
        addresses={DeliveryChannel.EMAIL: "live@example.com"},
        external_id="user_live",
    )
    erased = _notification(project_id=project_id, recipient_id=None)
    service, recipient_repository = _service(
        [erased, _notification(project_id=project_id, recipient_id=live.id)], [live]
    )

    page = await service.list_notifications(project_id)

    assert [item.recipient for item in page.items] == [None, "user_live"]
    # The erased row contributes no id: None would be a valid dict key and a
    # TypeError inside sorted().
    assert None not in recipient_repository.requested


@pytest.mark.asyncio
async def test_detail_of_an_erased_recipient_is_not_a_lookup() -> None:
    """A single erased notification renders null without querying for None."""
    project_id = uuid4()
    notification = _notification(project_id=project_id, recipient_id=None)
    service, recipient_repository = _service([notification], [])

    view = await service.get_notification_view(project_id, notification.id)

    assert view.recipient is None
    assert view.notification.id == notification.id
    assert recipient_repository.requested == []


@pytest.mark.asyncio
async def test_request_status_survives_an_erased_recipient() -> None:
    """The request still happened, so its status is answered rather than 404ed."""
    project_id = uuid4()
    intake = _intake(project_id=project_id, recipient_id=None)
    notification = _notification(
        project_id=project_id, recipient_id=None, transaction_id=intake.transaction_id
    )
    service, _ = _service([notification], [], intake)

    view = await service.get_request_status(project_id, intake.transaction_id)

    assert view.recipient is None
    assert view.intake.transaction_id == intake.transaction_id
    assert len(view.notifications) == 1


def test_intake_status_reports_null_identity_and_no_address() -> None:
    """An erased recipient yields nulls even for an address-based request."""
    project_id = uuid4()
    intake = _intake(project_id=project_id, recipient_id=None, channel_mode="addresses")

    response = IntakeStatusResponse.from_intake(
        intake, [_notification(project_id=project_id, recipient_id=None)], None
    )

    assert response.notifications[0].recipient is None
    assert response.notifications[0].address is None


def test_engagement_event_can_outlive_its_recipient() -> None:
    """An interaction with an erased recipient is recorded without attribution."""
    event = EngagementEvent.create(
        notification_id=uuid4(),
        project_id=uuid4(),
        recipient_id=None,
        event_type=EngagementEventType.OPEN,
        channel=DeliveryChannel.EMAIL,
        provider="resend",
        occurred_at=datetime.now(UTC),
    )

    assert EngagementEventResponse.from_entity(event).recipient_id is None
