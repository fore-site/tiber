"""Tests for the enum boundary-coercion pattern across the domain.

Every enum-typed field in the domain follows the same boundary contract,
matching Recipient's and Notification's established pattern: raw strings
from untyped callers are coerced via the enum call (so ``"EMAIL"``
normalizes to the member), members pass through unchanged (the call is
idempotent), and any value that is not a valid member raises the enum's
ValueError — never silently stored.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from uuid import uuid4

import pytest

from tiber.domain.entities import (
    DeliveryAttempt,
    EngagementEvent,
    NotificationTopic,
    Template,
    User,
)
from tiber.domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    UserRole,
)
from tiber.domain.exceptions import InvalidNotificationStateError
from tiber.domain.value_objects import (
    NotificationContent,
    RestrictedWindow,
    TopicTitle,
)

# --- User.role ---


def test_user_raw_role_string_is_coerced():
    """A raw wire-format role string arrives as the member."""
    user = User.create(email="a@b.io", role="admin")

    assert user.role is UserRole.ADMIN


def test_user_unknown_role_value_raises():
    """A string that is not a role value raises, never silently stored."""
    with pytest.raises(ValueError):
        User.create(email="a@b.io", role="superuser")


# --- Template.channel ---


def test_template_raw_channel_string_is_coerced():
    """A raw channel string arrives as the member, before the title check."""
    template = Template.create(
        project_id=uuid4(),
        name="welcome",
        channel="email",
        content=NotificationContent(title="Hi", body="Hello"),
    )

    assert template.channel is DeliveryChannel.EMAIL


def test_template_coercion_precedes_channel_title_check():
    """The email/title invariant applies to the coerced value.

    A raw 'email' without a title must be rejected by the same check
    that rejects the member — proving coercion ran before the check.
    """
    with pytest.raises(InvalidNotificationStateError, match="Title"):
        Template.create(
            project_id=uuid4(),
            name="welcome",
            channel="email",
            content=NotificationContent(body="Hello"),
        )


def test_template_cross_enum_impostor_raises():
    """A member of another enum is rejected: 'promotional' is not a channel."""
    with pytest.raises(ValueError):
        Template.create(
            project_id=uuid4(),
            name="welcome",
            channel=NotificationCategory.PROMOTIONAL,
            content=NotificationContent(body="Hello"),
        )


# --- EngagementEvent ---


def make_event(**overrides) -> EngagementEvent:
    """Build a valid engagement event with member-typed fields."""
    kwargs = dict(
        notification_id=uuid4(),
        project_id=uuid4(),
        recipient_id=uuid4(),
        event_type="open",
        channel="email",
        provider="postmark",
        occurred_at=datetime(2026, 9, 16, tzinfo=UTC),
        metadata={"ip": "1.2.3.4"},
    )
    kwargs.update(overrides)
    return EngagementEvent.create(**kwargs)


def test_event_raw_webhook_strings_are_coerced():
    """Untyped webhook payload strings arrive as members."""
    event = make_event()

    assert event.event_type == "open"  # StrEnum: equals its raw value
    assert event.channel is DeliveryChannel.EMAIL


def test_event_unknown_event_type_raises():
    """A typo'd webhook event type is rejected, not stored as garbage."""
    with pytest.raises(ValueError):
        make_event(event_type="clicked")  # the member is 'click'


# --- NotificationTopic.category ---


def test_topic_raw_category_string_is_coerced():
    """A raw category string arrives as the member."""
    topic = NotificationTopic.create(
        project_id=uuid4(),
        category="critical",
        title=TopicTitle("Password resets"),
    )

    assert topic.category is NotificationCategory.CRITICAL


def test_topic_unknown_category_value_raises():
    """A string that is not a category value raises."""
    with pytest.raises(ValueError):
        NotificationTopic.create(
            project_id=uuid4(),
            category="urgent",
            title=TopicTitle("Urgent"),
        )


# --- DeliveryAttempt ---


def make_attempt(**overrides) -> DeliveryAttempt:
    """Build a valid delivery attempt with member-typed fields."""
    kwargs = dict(
        notification_id=uuid4(),
        attempt_number=1,
        status="succeeded",
        channel="email",
        provider="postmark",
        recipient_address="jane@x.com",
    )
    kwargs.update(overrides)
    return DeliveryAttempt.create(**kwargs)


def test_attempt_raw_strings_are_coerced():
    """Raw status and channel strings arrive as members."""
    attempt = make_attempt()

    assert attempt.channel is DeliveryChannel.EMAIL
    assert attempt.status.value == "succeeded"


def test_attempt_unknown_status_value_raises():
    """A string that is not an attempt status raises."""
    with pytest.raises(ValueError):
        make_attempt(status="delivered")  # the member is 'succeeded'


# --- RestrictedWindow.channel (value object) ---


def test_window_raw_channel_string_is_coerced():
    """A raw channel string arrives as the member on the VO too."""
    window = RestrictedWindow(
        name="quiet-hours",
        window_start=time(22, 0),
        window_end=time(23, 0),
        channel="sms",
    )

    assert window.channel is DeliveryChannel.SMS


def test_window_unknown_channel_value_raises():
    """A string that is not a channel value raises at construction."""
    with pytest.raises(ValueError):
        RestrictedWindow(
            name="quiet-hours",
            window_start=time(22, 0),
            window_end=time(23, 0),
            channel="voice",
        )


# --- Cross-enum sanity for the two channels-typed fields used above ---


def test_delivery_channel_and_category_are_disjoint_vocabularies():
    """The same value string cannot smuggle between different enums.

    'promotional' is a category value but not a channel value; 'sms' is a
    channel value but not a category value. Value-lookup matches values,
    so cross-enum members cannot impersonate each other.
    """
    with pytest.raises(ValueError):
        DeliveryChannel(NotificationCategory.PROMOTIONAL)
    with pytest.raises(ValueError):
        NotificationCategory(DeliveryChannel.SMS)
