"""End-to-end delivery-constraint journeys.

The API is the only way configuration enters these tests; the intake and
dispatch processors are then run against the persisted state. That keeps the
assertions on the product contract rather than on repository internals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from tiber.application.ports.channel_provider import ProviderResult
from tiber.application.services.delivery import NotificationDeliveryProcessor
from tiber.application.services.intake_processor import IntakeProcessor
from tiber.application.services.policy import DeliveryPolicyGuard
from tiber.application.services.template import NotificationTemplateResolver
from tiber.domain.enums import NotificationStatus
from tiber.domain.policies import PolicyResolver
from tiber.infrastructure.ai.fallback import FallbackDecisionEngine
from tiber.infrastructure.models import RecipientModel
from tiber.infrastructure.repositories.sqlalchemy_delivery_attempt_repository import (
    SQLAlchemyDeliveryAttemptRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_delivery_constraint_repository import (
    SQLAlchemyDeliveryConstraintRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_notification_intake_repository import (
    SQLAlchemyNotificationIntakeRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_notification_topic_repository import (
    SQLAlchemyNotificationTopicRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)
from tiber.infrastructure.repositories.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.e2e

AUTH = {"Authorization": "Bearer e2e"}


class _Outbox:
    """Intake fan-out outbox that does not enqueue delivery jobs."""

    async def enqueue_dispatch(self, notification) -> None:
        return None


class _RecordingProvider:
    """Capture provider calls so a suppression can be proven by absence."""

    name = "recording"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(
        self,
        recipient_address: str,
        title: str | None,
        body: str,
        actions=(),
        images=(),
        metadata: dict | None = None,
        html_body: str | None = None,
    ) -> ProviderResult:
        self.calls.append(
            {
                "recipient_address": recipient_address,
                "title": title,
                "body": body,
                "html_body": html_body,
            }
        )
        return ProviderResult(success=True, provider_message_id="recording-id")

    async def health_check(self) -> bool:
        return True


def _headers(idempotency_key: str) -> dict:
    return {**AUTH, "Idempotency-Key": idempotency_key}


async def _recipient(session, project_id: UUID, external_id: str) -> RecipientModel:
    recipient = RecipientModel(
        project_id=project_id,
        external_id=external_id,
        addresses={
            "email": f"{external_id}@example.com",
            "in_app": external_id,
        },
    )
    session.add(recipient)
    await session.commit()
    return recipient


def _notification_body(external_id: str, send_at: datetime) -> dict:
    return {
        "recipient": external_id,
        "channels": ["email"],
        "category": "promotional",
        "content": {
            "title": "Your statement",
            "plain_text_body": "Open the app to view it.",
        },
        "send_at": send_at.isoformat(),
    }


async def _accept(client, project_id: UUID, external_id: str, send_at: datetime):
    response = await client.post(
        f"/v1/projects/{project_id}/notifications",
        headers=_headers(f"{external_id}-{send_at.timestamp()}"),
        json=_notification_body(external_id, send_at),
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["transaction_id"])


async def _process_intake(session, project_id: UUID, transaction_id: UUID):
    intake = await SQLAlchemyNotificationIntakeRepository(
        session
    ).get_by_transaction_id(transaction_id, project_id)
    assert intake is not None

    processor = IntakeProcessor(
        unit_of_work=SqlAlchemyUnitOfWork(session),
        intake_repository=SQLAlchemyNotificationIntakeRepository(session),
        notification_repository=SQLAlchemyNotificationRepository(session),
        recipient_repository=SQLAlchemyRecipientRepository(session),
        topic_repository=SQLAlchemyNotificationTopicRepository(session),
        template_resolver=NotificationTemplateResolver(
            SQLAlchemyTemplateRepository(session)
        ),
        policy_resolver=PolicyResolver(),
        decision_engine=FallbackDecisionEngine(),
        outbox=_Outbox(),
        constraint_repository=SQLAlchemyDeliveryConstraintRepository(session),
    )
    await processor.process(intake.id)
    return await SQLAlchemyNotificationRepository(session).list_by_transaction_id(
        transaction_id, project_id
    )


async def _dispatch_with_guard(session, project_id: UUID, notification):
    provider = _RecordingProvider()
    processor = NotificationDeliveryProcessor(
        unit_of_work=SqlAlchemyUnitOfWork(session),
        notification_repository=SQLAlchemyNotificationRepository(session),
        recipient_repository=SQLAlchemyRecipientRepository(session),
        delivery_attempt_repository=SQLAlchemyDeliveryAttemptRepository(session),
        provider=provider,
        policy_guard=DeliveryPolicyGuard(),
        constraint_repository=SQLAlchemyDeliveryConstraintRepository(session),
    )
    updated = await processor.process(notification.id, project_id=project_id)
    return updated, provider


async def test_recipient_blackout_suppresses_at_intake(
    client, project, session
) -> None:
    """A recipient-configured blackout is stored and enforced by the policy chain."""
    project_id = project.id
    await _recipient(session, project_id, "recipient-blackout")
    blackout = {
        "name": "personal holiday",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-01-02T00:00:00Z",
    }

    updated = await client.put(
        f"/v1/projects/{project_id}/recipients/preferences?recipient=recipient-blackout",
        headers=AUTH,
        json={"blackout_period": blackout},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["blackout_period"]["name"] == "personal holiday"

    transaction_id = await _accept(
        client,
        project_id,
        "recipient-blackout",
        datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    notifications = await _process_intake(session, project_id, transaction_id)

    assert len(notifications) == 1
    assert notifications[0].status is NotificationStatus.SUPPRESSED
    assert "blackout" in (notifications[0].suppression_reason or "")


async def test_recipient_quiet_hours_use_the_recipients_timezone(
    client, project, session
) -> None:
    """A timezone registered through the API moves the wall clock that decides.

    The window is 22:00-06:00 on the recipient's clock, and the recipient is in
    Tokyo. 14:30 UTC is 23:30 there, so the send is inside the window and is
    postponed to 06:05 Tokyo time. Evaluated on UTC it would not be restricted
    at all, so the assertion fails if the stored fact is ignored.
    """
    project_id = project.id
    registered = await client.post(
        f"/v1/projects/{project_id}/recipients",
        headers=AUTH,
        json={
            "external_id": "recipient-quiet",
            "addresses": {"email": "recipient-quiet@example.com"},
            "timezone": "Asia/Tokyo",
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["timezone"] == "Asia/Tokyo"

    quiet_hours = {
        "name": "night",
        "window_start": "22:00:00",
        "window_end": "06:00:00",
        "channel": "email",
    }
    updated = await client.put(
        f"/v1/projects/{project_id}/recipients/preferences?recipient=recipient-quiet",
        headers=AUTH,
        json={"quiet_hours": quiet_hours},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["quiet_hours"]["channel"] == "email"

    transaction_id = await _accept(
        client,
        project_id,
        "recipient-quiet",
        datetime(2026, 1, 1, 14, 30, tzinfo=UTC),
    )
    notifications = await _process_intake(session, project_id, transaction_id)

    assert len(notifications) == 1
    assert notifications[0].status is NotificationStatus.POSTPONED
    assert notifications[0].send_at == datetime(2026, 1, 1, 21, 5, tzinfo=UTC)


async def test_registration_rejects_an_unresolvable_timezone(client, project) -> None:
    """A zone the server cannot resolve is a 422, not a stored time bomb."""
    project_id = project.id

    rejected = await client.post(
        f"/v1/projects/{project_id}/recipients",
        headers=AUTH,
        json={"external_id": "recipient-bad-zone", "timezone": "Mars/Olympus_Mons"},
    )

    assert rejected.status_code == 422, rejected.text
    assert "timezone" in rejected.text


async def test_patch_restates_and_withdraws_the_timezone(client, project) -> None:
    """PATCH is partial: omitted keeps the fact, null records it unknown."""
    project_id = project.id
    registered = await client.post(
        f"/v1/projects/{project_id}/recipients",
        headers=AUTH,
        json={"external_id": "recipient-patch", "addresses": {"email": "a@b.co"}},
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["timezone"] is None

    stated = await client.patch(
        f"/v1/projects/{project_id}/recipients?recipient=recipient-patch",
        headers=AUTH,
        json={"addresses": {"email": "a@b.co"}, "timezone": "Europe/Lisbon"},
    )
    assert stated.status_code == 200, stated.text
    assert stated.json()["timezone"] == "Europe/Lisbon"

    untouched = await client.patch(
        f"/v1/projects/{project_id}/recipients?recipient=recipient-patch",
        headers=AUTH,
        json={"addresses": {"email": "a@b.co"}},
    )
    assert untouched.status_code == 200, untouched.text
    assert untouched.json()["timezone"] == "Europe/Lisbon"

    withdrawn = await client.patch(
        f"/v1/projects/{project_id}/recipients?recipient=recipient-patch",
        headers=AUTH,
        json={"addresses": {"email": "a@b.co"}, "timezone": None},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["timezone"] is None


async def test_project_constraint_can_be_replaced_and_read_back(
    client, project
) -> None:
    """The singleton resource returns the permissive default, then the update."""
    project_id = project.id

    default = await client.get(
        f"/v1/projects/{project_id}/delivery-constraint", headers=AUTH
    )
    assert default.status_code == 200
    assert default.json() == {
        "timezone": "UTC",
        "blackout_periods": [],
        "quiet_hours": [],
    }

    created = await client.put(
        f"/v1/projects/{project_id}/delivery-constraint",
        headers=AUTH,
        json={
            "timezone": "Europe/London",
            "blackout_periods": [
                {
                    "name": "launch freeze",
                    "start": "2027-01-01T00:00:00Z",
                    "end": "2027-01-01T12:00:00Z",
                }
            ],
            "quiet_hours": [
                {
                    "name": "overnight",
                    "window_start": "22:00:00",
                    "window_end": "07:00:00",
                    "channel": "email",
                }
            ],
        },
    )
    assert created.status_code == 200, created.text

    read_back = await client.get(
        f"/v1/projects/{project_id}/delivery-constraint", headers=AUTH
    )
    assert read_back.status_code == 200
    assert read_back.json() == created.json()
    assert read_back.json()["timezone"] == "Europe/London"


async def test_project_blackout_suppresses_at_intake(client, project, session) -> None:
    """A project-level blackout configured through the API blocks the send."""
    project_id = project.id
    await _recipient(session, project_id, "project-blackout")

    configured = await client.put(
        f"/v1/projects/{project_id}/delivery-constraint",
        headers=AUTH,
        json={
            "timezone": "UTC",
            "blackout_periods": [
                {
                    "name": "maintenance",
                    "start": "2026-02-01T00:00:00Z",
                    "end": "2026-02-02T00:00:00Z",
                }
            ],
        },
    )
    assert configured.status_code == 200, configured.text

    transaction_id = await _accept(
        client,
        project_id,
        "project-blackout",
        datetime(2026, 2, 1, 9, 0, tzinfo=UTC),
    )
    notifications = await _process_intake(session, project_id, transaction_id)

    assert len(notifications) == 1
    assert notifications[0].status is NotificationStatus.SUPPRESSED
    assert "maintenance" in (notifications[0].suppression_reason or "")


async def test_dispatch_guard_reads_constraints_saved_after_intake(
    client, project, session
) -> None:
    """The worker re-checks project configuration that changed after intake."""
    project_id = project.id
    await _recipient(session, project_id, "dispatch-blackout")
    now = datetime.now(UTC).replace(microsecond=0)

    transaction_id = await _accept(
        client, project_id, "dispatch-blackout", now - timedelta(minutes=1)
    )
    notifications = await _process_intake(session, project_id, transaction_id)
    assert len(notifications) == 1
    assert notifications[0].status is NotificationStatus.PENDING

    configured = await client.put(
        f"/v1/projects/{project_id}/delivery-constraint",
        headers=AUTH,
        json={
            "timezone": "UTC",
            "blackout_periods": [
                {
                    "name": "late freeze",
                    "start": (now - timedelta(hours=1)).isoformat(),
                    "end": (now + timedelta(hours=1)).isoformat(),
                }
            ],
        },
    )
    assert configured.status_code == 200, configured.text

    updated, provider = await _dispatch_with_guard(
        session, project_id, notifications[0]
    )

    assert updated.status is NotificationStatus.SUPPRESSED
    assert "late freeze" in (updated.suppression_reason or "")
    assert provider.calls == []
