"""Mapping tests for the notification intake persistence adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from tiber.domain.entities.notification_intake import NotificationIntake
from tiber.domain.enums import DeliveryChannel, IntakeStatus, NotificationCategory
from tiber.domain.value_objects import NotificationContent
from tiber.domain.value_objects.intake import (
    DecisionConstraints,
    IntakePayload,
    NotificationPlan,
    ResolvedTopic,
)
from tiber.infrastructure.repositories.sqlalchemy_notification_intake_repository import (
    SQLAlchemyNotificationIntakeRepository,
)


def _intake() -> NotificationIntake:
    """Build a representative intake containing every persisted value object."""
    topic = ResolvedTopic(
        id=uuid4(),
        slug="account-alerts",
        category=NotificationCategory.INFORMATIONAL,
    )
    payload = IntakePayload(
        category=NotificationCategory.INFORMATIONAL,
        topic=topic,
        channels=(DeliveryChannel.EMAIL,),
        template_variables={"account_name": "Ada"},
        template_id=uuid4(),
        template_slug="account-alert",
        group_key="account-123",
        send_at=datetime(2030, 1, 2, 3, 4, tzinfo=UTC),
    )
    constraints = DecisionConstraints(
        allowed_categories=frozenset({NotificationCategory.INFORMATIONAL}),
        default_category=NotificationCategory.INFORMATIONAL,
        channel_mode="client",
        feasible_channels=frozenset({DeliveryChannel.EMAIL}),
        max_channels=1,
    )
    return NotificationIntake.create(
        project_id=uuid4(),
        recipient_id=uuid4(),
        payload=payload,
        constraints=constraints,
        request_fingerprint="fingerprint",
        idempotency_key="request-123",
    )


def test_notification_intake_model_round_trip_preserves_received_state() -> None:
    """The accepted request and its JSON snapshots survive ORM translation."""
    intake = _intake()

    model = SQLAlchemyNotificationIntakeRepository._to_model(intake)
    restored = SQLAlchemyNotificationIntakeRepository._to_entity(model)

    assert restored == intake
    assert restored.status is IntakeStatus.RECEIVED
    assert model.payload["channels"] == [DeliveryChannel.EMAIL.value]
    assert model.constraints["channel_mode"] == "client"
    assert model.plan is None


def test_notification_intake_model_round_trip_preserves_completed_plan() -> None:
    """A claimed, planned, and completed intake preserves nested plan data."""
    intake = _intake()
    now = datetime(2030, 1, 2, 3, 5, tzinfo=UTC)
    topic = intake.payload.topic
    assert topic is not None

    plan = NotificationPlan(
        category=NotificationCategory.INFORMATIONAL,
        category_source="client",
        topic=topic,
        topic_source="client",
        channels=(DeliveryChannel.EMAIL,),
        channel_source="client",
        send_at={DeliveryChannel.EMAIL: now + timedelta(minutes=1)},
        model_version="rules-v1",
    )
    completed = intake.claim(now, timedelta(minutes=5)).with_plan(plan).complete(now)

    model = SQLAlchemyNotificationIntakeRepository._to_model(completed)
    restored = SQLAlchemyNotificationIntakeRepository._to_entity(model)

    assert restored == completed
    assert restored.status is IntakeStatus.COMPLETED
    assert restored.plan is not None
    assert restored.plan.send_at[DeliveryChannel.EMAIL] == now + timedelta(minutes=1)


def test_notification_intake_model_serializes_direct_content() -> None:
    """Direct content is persisted distinctly from template-based payloads."""
    intake = _intake()
    payload = IntakePayload(
        channels=(DeliveryChannel.EMAIL,),
        content=NotificationContent(
            title="Hello",
            body="Your account changed.",
        ),
    )
    direct = NotificationIntake.create(
        project_id=intake.project_id,
        recipient_id=intake.recipient_id,
        payload=payload,
        constraints=intake.constraints,
        request_fingerprint=intake.request_fingerprint,
    )

    model = SQLAlchemyNotificationIntakeRepository._to_model(direct)
    restored = SQLAlchemyNotificationIntakeRepository._to_entity(model)

    assert restored == direct
    assert model.payload["content"] == {
        "title": "Hello",
        "body": "Your account changed.",
        "actions": [],
        "images": [],
    }
