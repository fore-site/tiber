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
from tiber.domain.exceptions import InvalidNotificationStateError
from tiber.domain.value_objects import NotificationContent


def make_notification(**overrides) -> Notification:
    """Build a valid promotional email notification, with overrides."""
    kwargs = dict(
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.PROMOTIONAL,
        content=NotificationContent(title="Hi", body="Hello"),
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
        content=NotificationContent(title="Hi", body="Hello"),
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


# --- group_key: opaque identity of the logical thing this send is about ---


def test_group_key_is_none_by_default_and_round_trips_through_create():
    """group_key is optional and accepted as given — it is never parsed."""
    default = make_notification()
    assert default.group_key is None

    notification = make_notification(group_key="order-1234")
    assert notification.group_key == "order-1234"


def test_group_key_accepts_arbitrary_opaque_strings():
    """No structure is imposed: any non-empty string is a valid identity."""
    for key in ("order-1234", "post_42/comments", "user:7:cart"):
        assert make_notification(group_key=key).group_key == key


def test_group_key_rejects_blank_string():
    """An empty or whitespace key is not an identity — reject, don't coerce."""
    with pytest.raises(InvalidNotificationStateError, match="group_key"):
        make_notification(group_key="   ")


def test_group_key_rejects_over_length_string():
    """The 255-char ceiling mirrors the persistence column's bound."""
    with pytest.raises(InvalidNotificationStateError, match="group_key"):
        make_notification(group_key="x" * 256)


def test_rehydrated_group_key_is_preserved():
    """group_key is persisted state: a DB round-trip must keep it.

    The collapse/dedup/learning consumers query it from storage, so a
    rehydrated row that lost the key would silently ungroup its sends.
    """
    restored = Notification.reconstitute(
        id=uuid4(),
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.PROMOTIONAL,
        content=NotificationContent(title="Hi", body="Hello"),
        status=NotificationStatus.PENDING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        template_id=None,
        template_variables=None,
        group_key="order-1234",
        idempotency_key=None,
        send_at=None,
        send_time_basis=SendTimeBasis.ML_PREDICTED,
        policy_violation_reason=None,
        cancellation_reason=None,
        failure_reason=None,
        delivered_at=None,
    )

    assert restored.group_key == "order-1234"


# --- cancellation carries its reason ---


def test_mark_cancelled_is_legal_without_a_reason():
    """Clients cancel freely, without documenting why.

    The optional reason exists for system-initiated cancellations (digest
    absorption, future latest-wins supersession), where it is a system
    fact Tiber generated — not client documentation.
    """
    cancelled = make_notification().mark_cancelled()

    assert cancelled.status is NotificationStatus.CANCELLED
    assert cancelled.cancellation_reason is None


def test_mark_cancelled_carries_the_reason():
    """The reason is stored on the row, not just in logs."""
    cancelled = make_notification().mark_cancelled("superseded by order-1235")

    assert cancelled.status is NotificationStatus.CANCELLED
    assert cancelled.cancellation_reason == "superseded by order-1235"


def test_cancellation_reason_only_set_when_cancelled():
    """A non-cancelled notification cannot carry a cancellation reason.

    Direct instantiation path: create() never accepts status or the reason,
    so this invariant guards the rehydration/reconstitution boundary.
    """
    with pytest.raises(InvalidNotificationStateError, match="cancellation_reason"):
        Notification(
            project_id=uuid4(),
            recipient_id=uuid4(),
            correlation_id=uuid4(),
            channel=DeliveryChannel.EMAIL,
            category=NotificationCategory.PROMOTIONAL,
            content=NotificationContent(title="Hi", body="Hello"),
            status=NotificationStatus.PENDING,
            cancellation_reason="not cancelled yet",
        )


# --- send_time_basis is stored state, not a derived value ---


def test_rehydrated_ml_predicted_with_send_at_keeps_its_basis():
    """The design-proof: (send_at=T, ML_PREDICTED) survives rehydration.

    The old derived implementation re-classified any send_at as EXPLICIT,
    so Tiber-scheduled notifications lost their provenance on the first
    DB round-trip. Provenance must be queryable to measure the predictor.
    """
    predicted_time = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)

    restored = Notification.reconstitute(
        id=uuid4(),
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.PROMOTIONAL,
        content=NotificationContent(title="Hi", body="Hello"),
        status=NotificationStatus.PENDING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        template_id=None,
        template_variables=None,
        group_key=None,
        idempotency_key=None,
        send_at=predicted_time,
        send_time_basis=SendTimeBasis.ML_PREDICTED,
        policy_violation_reason=None,
        cancellation_reason=None,
        failure_reason=None,
        delivered_at=None,
    )

    assert restored.send_time_basis is SendTimeBasis.ML_PREDICTED
    assert restored.send_at == predicted_time


def test_rehydrate_explicit_without_send_at_is_rejected():
    """EXPLICIT claims a client schedule: no time means corrupt state."""
    with pytest.raises(InvalidNotificationStateError, match="send_at"):
        Notification.reconstitute(
            id=uuid4(),
            project_id=uuid4(),
            recipient_id=uuid4(),
            correlation_id=uuid4(),
            channel=DeliveryChannel.EMAIL,
            category=NotificationCategory.PROMOTIONAL,
            content=NotificationContent(title="Hi", body="Hello"),
            status=NotificationStatus.PENDING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            template_id=None,
            template_variables=None,
            group_key=None,
            idempotency_key=None,
            send_at=None,
            send_time_basis=SendTimeBasis.EXPLICIT,
            policy_violation_reason=None,
            cancellation_reason=None,
            failure_reason=None,
            delivered_at=None,
        )


def test_immediate_basis_requires_critical_category():
    """IMMEDIATE is the CRITICAL-only path: not representable elsewhere."""
    with pytest.raises(InvalidNotificationStateError, match="IMMEDIATE"):
        Notification(
            project_id=uuid4(),
            recipient_id=uuid4(),
            correlation_id=uuid4(),
            channel=DeliveryChannel.EMAIL,
            category=NotificationCategory.PROMOTIONAL,
            content=NotificationContent(title="Hi", body="Hello"),
            send_time_basis=SendTimeBasis.IMMEDIATE,
        )


def test_critical_basis_is_pinned_to_immediate():
    """CRITICAL must be IMMEDIATE — even if a caller asserts otherwise."""
    with pytest.raises(InvalidNotificationStateError, match="CRITICAL"):
        Notification(
            project_id=uuid4(),
            recipient_id=uuid4(),
            correlation_id=uuid4(),
            channel=DeliveryChannel.EMAIL,
            category=NotificationCategory.CRITICAL,
            content=NotificationContent(title="Hi", body="Hello"),
            send_time_basis=SendTimeBasis.ML_PREDICTED,
        )


def test_intake_classification_still_works():
    """The intake rule is unchanged in effect: absent basis self-classifies."""
    explicit = make_notification(send_at=datetime(2026, 9, 19, 9, 0, tzinfo=UTC))
    immediate = make_notification(category=NotificationCategory.CRITICAL)
    ml = make_notification()

    assert explicit.send_time_basis is SendTimeBasis.EXPLICIT
    assert immediate.send_time_basis is SendTimeBasis.IMMEDIATE
    assert ml.send_time_basis is SendTimeBasis.ML_PREDICTED


# --- schedule(): the ML path's transition ---


def test_schedule_sets_time_and_preserves_basis():
    """Prediction attaches a time without changing provenance."""
    notification = make_notification()
    predicted = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)

    scheduled = notification.schedule(predicted)

    assert scheduled.send_at == predicted
    assert scheduled.send_time_basis is SendTimeBasis.ML_PREDICTED
    assert scheduled.status is NotificationStatus.PENDING


def test_schedule_rejects_client_scheduled_notification():
    """EXPLICIT is client-owned: the ML path cannot override it."""
    notification = make_notification(send_at=datetime(2026, 9, 19, 9, 0, tzinfo=UTC))

    with pytest.raises(InvalidNotificationStateError, match="ML_PREDICTED"):
        notification.schedule(datetime(2026, 9, 20, 9, 0, tzinfo=UTC))


def test_schedule_rejects_critical():
    """CRITICAL dispatches immediately; there is nothing to schedule."""
    notification = make_notification(category=NotificationCategory.CRITICAL)

    with pytest.raises(InvalidNotificationStateError, match="ML_PREDICTED"):
        notification.schedule(datetime(2026, 9, 20, 9, 0, tzinfo=UTC))


def test_schedule_rejects_naive_datetime():
    """Same tz-awareness rule as client-supplied send_at."""
    with pytest.raises(InvalidNotificationStateError, match="timezone"):
        make_notification().schedule(datetime(2026, 9, 20, 9, 0))


def test_reprediction_replaces_the_predicted_time():
    """Re-prediction is allowed until dispatch: each call replaces the time."""
    notification = make_notification().schedule(
        datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
    )

    rescheduled = notification.schedule(datetime(2026, 9, 19, 16, 0, tzinfo=UTC))

    assert rescheduled.send_at == datetime(2026, 9, 19, 16, 0, tzinfo=UTC)
    assert rescheduled.send_time_basis is SendTimeBasis.ML_PREDICTED
