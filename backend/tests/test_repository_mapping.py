"""ORM mapping round-trips for the template and topic repositories.

These run without a database: they exercise the model<->entity translation,
which is where the previous template repository silently diverged from the
aggregate (single channel/subject/body versus per-channel variants).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from tiber.domain.entities import NotificationTopic, Template
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.value_objects import NotificationContent, TemplateVariant
from tiber.infrastructure.repositories.sqlalchemy_notification_topic_repository import (
    SQLAlchemyNotificationTopicRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)


def test_template_model_round_trip_preserves_variants():
    """All variants and their content survive the ORM translation."""
    template = Template.create(
        project_id=uuid4(),
        name="Order Update",
        variants=[
            TemplateVariant(
                channel=DeliveryChannel.EMAIL,
                content=NotificationContent(
                    title="Hi {{first_name}}", body="Order {{order_id}} shipped"
                ),
            ),
            TemplateVariant(
                channel=DeliveryChannel.SMS,
                content=NotificationContent(body="Order shipped"),
            ),
        ],
    )

    model = SQLAlchemyTemplateRepository._to_model(template)
    restored = SQLAlchemyTemplateRepository._to_entity(model)

    assert restored == template
    # JSONB keys are strings; the entity keys must be enum members again.
    assert set(restored.variants) == {DeliveryChannel.EMAIL, DeliveryChannel.SMS}
    assert model.variants["email"]["title"] == "Hi {{first_name}}"


def test_template_model_stores_the_persisted_slug():
    """The derived slug is written to its own column."""
    template = Template.create(
        project_id=uuid4(),
        name="Order Update",
        variants=[
            TemplateVariant(
                channel=DeliveryChannel.SMS,
                content=NotificationContent(body="Shipped"),
            )
        ],
    )

    model = SQLAlchemyTemplateRepository._to_model(template)

    assert model.template_slug == "order-update"


def test_topic_model_round_trip_restores_enum_and_slug():
    """Category and slug survive the trip through plain strings."""
    now = datetime.now(UTC)
    topic = NotificationTopic.reconstitute(
        id=uuid4(),
        project_id=uuid4(),
        category=NotificationCategory.CRITICAL,
        title="Password Resets",
        topic_slug="password-resets",
        created_at=now,
        updated_at=now,
    )

    model = SQLAlchemyNotificationTopicRepository._to_model(topic)
    restored = SQLAlchemyNotificationTopicRepository._to_entity(model)

    assert restored == topic
    assert restored.category is NotificationCategory.CRITICAL
    assert restored.topic_slug == "password-resets"
