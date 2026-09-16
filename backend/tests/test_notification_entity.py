"""Tests for Notification entity enum coercion.

The entity accepts raw strings for its enum-typed fields (channel,
category, status) at the same boundary as Recipient: values are coerced
via the enum call, so an unknown value raises the enum's ValueError and
a member passes through unchanged (the call is idempotent).

The ordering property is pinned too: coercion runs before any check
reads the fields, so a raw ``"critical"`` string derives the same
send_time_basis as the member would.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tiber.domain.entities import Notification
from tiber.domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    NotificationStatus,
    SendTimeBasis,
)
from tiber.domain.value_objects import NotificationContent


def make_notification(**overrides) -> Notification:
    """Build a valid promotional email notification, with overrides."""
    kwargs = dict(
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.PROMOTIONAL,
        content=NotificationContent(subject="Hi", body="Hello"),
    )
    kwargs.update(overrides)
    return Notification.create(**kwargs)


# --- Raw strings are coerced to members ---


def test_raw_string_fields_are_coerced_to_members():
    """Raw wire-format strings arrive as the corresponding enum members.

    create() has no status parameter by design (states arise only through
    transitions), so status coercion is pinned separately below.
    """
    notification = make_notification(channel="email", category="promotional")

    assert notification.channel is DeliveryChannel.EMAIL
    assert notification.category is NotificationCategory.PROMOTIONAL


def test_raw_status_string_is_coerced_on_direct_instantiation():
    """Direct construction accepts a raw status string, coerced to a member."""
    notification = Notification(
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel="email",
        category="promotional",
        content=NotificationContent(subject="Hi", body="Hello"),
        status="pending",
    )

    assert notification.status is NotificationStatus.PENDING


def test_raw_strings_are_normalized_to_lowercase():
    """Uppercase wire values normalize through .lower() before the enum call."""
    notification = make_notification(channel="EMAIL", category="PROMOTIONAL")

    assert notification.channel is DeliveryChannel.EMAIL
    assert notification.category is NotificationCategory.PROMOTIONAL


def test_members_pass_through_unchanged():
    """The enum call is idempotent: a member re-derives the same member."""
    notification = make_notification()

    assert notification.channel is DeliveryChannel.EMAIL
    assert notification.category is NotificationCategory.PROMOTIONAL


# --- Invalid values are rejected ---


def test_unknown_category_value_raises():
    """A string that is not a category value raises the enum's ValueError."""
    with pytest.raises(ValueError):
        make_notification(category="transactional")


def test_unknown_channel_value_raises():
    """A string that is not a channel value raises the enum's ValueError."""
    with pytest.raises(ValueError):
        make_notification(channel="fax")


def test_cross_enum_impostor_raises():
    """A member of another enum does not match by value and raises.

    Value-lookup compares values, not types: 'sms' is a valid DeliveryChannel
    value but not a NotificationCategory value, so passing the wrong enum's
    member is rejected rather than silently accepted.
    """
    with pytest.raises(ValueError):
        make_notification(category=DeliveryChannel.SMS)


# --- Coercion ordering: before any check reads the fields ---


def test_raw_critical_string_derives_immediate_basis():
    """Coercion runs before the derivation reads category.

    A raw 'critical' with no send_at must derive IMMEDIATE. If the
    derivation saw the pre-coercion value, the membership-derived branch
    would never fire and the basis would come out ML_PREDICTED instead.
    """
    notification = make_notification(category="critical")

    assert notification.category is NotificationCategory.CRITICAL
    assert notification.send_time_basis is SendTimeBasis.IMMEDIATE


def test_raw_critical_string_with_send_at_is_rejected():
    """The CRITICAL+send_at invariant applies to the coerced value too."""
    with pytest.raises(Exception, match="send_at"):
        make_notification(
            category="critical",
            send_at=datetime(2026, 9, 16, 12, 0, tzinfo=UTC),
        )
