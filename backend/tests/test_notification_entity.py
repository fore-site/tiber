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


# --- client context: ML feature payload ---


def test_context_is_none_by_default_and_accepted_when_valid():
    """Context is optional, and a flat str->str dict is accepted as given."""
    default = make_notification()
    assert default.context is None

    ctx_payload = {"segment": "power_user", "campaign_id": "spring-26"}
    notification = make_notification(context=ctx_payload)
    assert notification.context == ctx_payload


def test_context_rejects_non_string_values():
    """Nested structures are not representable: values must be strings.

    A flat payload keeps the ML feature schema legible — a client wanting
    structure encodes it into the string (e.g. JSON) themselves.
    """
    with pytest.raises(Exception, match="context"):
        make_notification(context={"experiment": {"arm": "B"}})


def test_context_rejects_non_string_keys():
    """Keys must be strings too, so the payload serializes predictably."""
    with pytest.raises(Exception, match="context"):
        make_notification(context={7: "lucky"})


def test_context_rejects_non_dict_input():
    """A list or scalar passed as context is rejected, not coerced."""
    with pytest.raises(Exception, match="context"):
        make_notification(context=["not", "a", "dict"])


def test_reconstitute_drops_context():
    """Context is intake-time state, not persisted state.

    reconstitute() does not accept it: the ML feature payload has no
    storage home yet (deferred to the ML phase, separate table, never
    EngagementEvent), so a rehydrated notification legitimately reads as
    context-less. The entity's in-memory contract still accepts context
    at create()-time for the future write path.
    """
    created = make_notification(context={"segment": "power_user"})

    restored = Notification.reconstitute(
        id=created.id,
        project_id=created.project_id,
        recipient_id=created.recipient_id,
        correlation_id=created.correlation_id,
        channel=created.channel,
        category=created.category,
        content=created.content,
        status=created.status,
        created_at=created.created_at,
        updated_at=created.updated_at,
        template_id=created.template_id,
        template_variables=created.template_variables,
        idempotency_key=created.idempotency_key,
        send_at=created.send_at,
        send_time_basis=created.send_time_basis,
        policy_violation_reason=created.policy_violation_reason,
        failure_reason=created.failure_reason,
        delivered_at=created.delivered_at,
    )

    assert restored.context is None


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
        idempotency_key=None,
        send_at=predicted_time,
        send_time_basis=SendTimeBasis.ML_PREDICTED,
        policy_violation_reason=None,
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
            idempotency_key=None,
            send_at=None,
            send_time_basis=SendTimeBasis.EXPLICIT,
            policy_violation_reason=None,
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
