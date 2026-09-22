"""Tests for the time-based domain policy rules.

``BlackoutPeriodRule`` and ``RestrictedWindowsRule`` are the most subtle
rules in the domain: timezone projection, midnight wraparound, inclusive
boundaries, channel filtering, and two send-time branches (``send_at`` vs
``ctx.now``). Every test pins exactly one fact with a fixed
``PolicyContext.now`` — no wall clock, no monkeypatching.

These tests encode deliberate decisions, not accidents:

- boundaries are INCLUSIVE (a send exactly at a boundary is inside);
- a window with ``window_start > window_end`` spans midnight;
- windows are additive prohibitions — any match rejects, so the verdict
  must be independent of registration order (see the regression test);
- the first matching window in registration order supplies the reason.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import uuid4

import pytest

from tiber.domain.entities import DeliveryConstraint, Notification, Recipient
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.policies import PolicyContext
from tiber.domain.policies.rules import BlackoutPeriodRule, RestrictedWindowsRule
from tiber.domain.value_objects import (
    BlackoutPeriod,
    NotificationContent,
    RecipientPreferences,
    RestrictedWindow,
)


def make_ctx(
    *,
    channel: DeliveryChannel = DeliveryChannel.SMS,
    send_at: datetime | None = None,
    now: datetime = datetime(2026, 9, 15, 23, 0, tzinfo=UTC),
    constraint: DeliveryConstraint | None = None,
    category: NotificationCategory = NotificationCategory.PROMOTIONAL,
) -> PolicyContext:
    """Build a policy context with a fixed clock and no consent interference."""
    notification = Notification.create(
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=channel,
        category=category,
        content=NotificationContent(
            title="Hi" if channel == DeliveryChannel.EMAIL else None,
            body="Hello",
        ),
        send_at=send_at,
    )
    recipient = Recipient.reconstitute(
        id=uuid4(),
        project_id=notification.project_id,
        addresses={channel: "+2348012345678"},
        preferences=RecipientPreferences(),
        external_id=None,
        timezone=None,
        language=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        archived_at=None,
    )
    return PolicyContext(
        notification=notification,
        recipient=recipient,
        delivery_constraint=constraint,
        now=now,
    )


def sms_window(start: time, end: time) -> RestrictedWindow:
    """Build a restricted window bound to the SMS channel."""
    return RestrictedWindow(
        name="restriction",
        window_start=start,
        window_end=end,
        channel=DeliveryChannel.SMS,
    )


def blackout(start: date, end: date, name: str = "holiday") -> BlackoutPeriod:
    """Build a blackout period spanning the given inclusive date range."""
    return BlackoutPeriod(name=name, start_date=start, end_date=end)


def constraint_with(
    windows: tuple[RestrictedWindow, ...] = (),
    blackouts: tuple[BlackoutPeriod, ...] = (),
    tz: str = "UTC",
) -> DeliveryConstraint:
    """Build a project delivery constraint holding the given windows/periods."""
    return DeliveryConstraint.create(
        project_id=uuid4(),
        restricted_windows=list(windows),
        blackout_periods=list(blackouts),
        timezone=tz,
    )


# --- RestrictedWindow VO: degenerate windows are unrepresentable ---


def test_single_instant_window_is_rejected_at_construction():
    """Pin that window_start == window_end is invalid config, rejected early."""
    with pytest.raises(ValueError):
        RestrictedWindow(
            name="x",
            window_start=time(9, 0),
            window_end=time(9, 0),
            channel=DeliveryChannel.SMS,
        )


# --- BlackoutPeriod VO: inverted ranges are unrepresentable ---


def test_inverted_blackout_period_is_rejected_at_construction():
    """Pin that start_date > end_date is invalid config, rejected early.

    An inverted range can never match a send_date, so without this guard the
    blackout silently blackouts nothing forever.
    """
    with pytest.raises(ValueError):
        BlackoutPeriod(
            name="x", start_date=date(2026, 9, 17), end_date=date(2026, 9, 15)
        )


# --- RestrictedWindowsRule: membership ---

LUNCH = sms_window(time(9, 0), time(12, 0))
OVERNIGHT = sms_window(time(22, 0), time(6, 0))  # spans midnight


async def test_window_rejects_when_send_time_inside():
    """Pin that a send inside a channel-matching window rejects."""
    ctx = make_ctx(
        constraint=constraint_with(windows=(LUNCH,)),
        now=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert not decision.allowed
    assert decision.rule == "restricted_windows"


async def test_window_allows_when_send_time_outside_all_windows():
    """Pin that a send outside every window for the channel allows."""
    ctx = make_ctx(
        constraint=constraint_with(windows=(LUNCH,)),
        now=datetime(2026, 9, 15, 12, 1, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert decision.allowed


async def test_window_start_boundary_is_inclusive():
    """Pin that a send exactly at window_start is inside the restriction."""
    ctx = make_ctx(
        constraint=constraint_with(windows=(LUNCH,)),
        now=datetime(2026, 9, 15, 9, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert not decision.allowed


async def test_window_end_boundary_is_inclusive():
    """Pin that a send exactly at window_end is inside the restriction."""
    ctx = make_ctx(
        constraint=constraint_with(windows=(LUNCH,)),
        now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert not decision.allowed


# --- RestrictedWindowsRule: additive prohibitions (OR-composition) ---


async def test_window_rejects_inside_second_window_after_first_window_misses():
    """The regression test for the order-dependent-verdict bug.

    23:00 misses lunch (09:00-12:00) but hits overnight (22:00-06:00). The
    pre-loop implementation returned allow() after the first non-matching
    window, so this exact scenario allowed the send whenever lunch was
    registered first. This test fails on that code.
    """
    ctx = make_ctx(
        constraint=constraint_with(windows=(LUNCH, OVERNIGHT)),
        now=datetime(2026, 9, 15, 23, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert not decision.allowed
    assert "22:00:00" in decision.reason
    assert "06:00:00" in decision.reason


async def test_window_verdict_is_independent_of_registration_order():
    """Pin that same facts with reordered windows give identical verdict AND reason."""
    rule = RestrictedWindowsRule()
    first = await rule.evaluate(
        make_ctx(constraint=constraint_with(windows=(LUNCH, OVERNIGHT)))
    )
    second = await rule.evaluate(
        make_ctx(constraint=constraint_with(windows=(OVERNIGHT, LUNCH)))
    )

    assert (first.allowed, first.reason) == (second.allowed, second.reason)


async def test_window_first_matching_window_supplies_the_reason():
    """Pin that with overlapping matches, the first window in registration order wins."""
    wider = sms_window(time(8, 0), time(13, 0))
    ctx = make_ctx(
        constraint=constraint_with(windows=(LUNCH, wider)),
        now=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert not decision.allowed
    assert "09:00:00" in decision.reason  # LUNCH's bounds, not wider's


# --- RestrictedWindowsRule: midnight wraparound ---


async def test_window_midnight_spanning_window_rejects_before_midnight():
    """Pin that 23:00 falls inside a 22:00->06:00 window."""
    ctx = make_ctx(
        constraint=constraint_with(windows=(OVERNIGHT,)),
        now=datetime(2026, 9, 15, 23, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert not decision.allowed


async def test_window_midnight_spanning_window_rejects_after_midnight():
    """Pin that 01:00 falls inside a 22:00->06:00 window."""
    ctx = make_ctx(
        constraint=constraint_with(windows=(OVERNIGHT,)),
        now=datetime(2026, 9, 15, 1, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert not decision.allowed


async def test_window_midnight_spanning_window_allows_between_boundaries():
    """Pin that noon falls outside 22:00->06:00 even though 12:00 > 06:00."""
    ctx = make_ctx(
        constraint=constraint_with(windows=(OVERNIGHT,)),
        now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert decision.allowed


# --- RestrictedWindowsRule: channel filter ---


async def test_window_ignores_windows_for_other_channels():
    """Pin that an SMS notification is not judged against an EMAIL window."""
    email_quiet = RestrictedWindow(
        name="email-quiet",
        window_start=time(21, 0),
        window_end=time(23, 0),
        channel=DeliveryChannel.EMAIL,
    )
    ctx = make_ctx(
        channel=DeliveryChannel.SMS,
        constraint=constraint_with(windows=(email_quiet,)),
        now=datetime(2026, 9, 15, 22, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert decision.allowed


# --- RestrictedWindowsRule: send-time branch ---


async def test_window_send_at_inside_rejects_even_when_ctx_now_outside():
    """Pin that send_at's moment is judged, not the evaluation moment."""
    ctx = make_ctx(
        constraint=constraint_with(windows=(LUNCH,)),
        now=datetime(2026, 9, 14, 23, 0, tzinfo=UTC),  # day before: outside
        send_at=datetime(2026, 9, 15, 10, 30, tzinfo=UTC),  # inside lunch
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert not decision.allowed


async def test_window_send_at_outside_allows_even_when_ctx_now_inside():
    """Pin that windows are time-of-day prohibitions: send_at's date is irrelevant.

    now (10:00) is inside lunch; send_at (14:00 on any date) is outside. The
    rule must judge the send moment's wall clock, not the evaluation moment's.
    """
    ctx = make_ctx(
        constraint=constraint_with(windows=(LUNCH,)),
        now=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),  # inside lunch
        send_at=datetime(2026, 9, 16, 14, 0, tzinfo=UTC),  # 14:00: outside
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert decision.allowed


# --- RestrictedWindowsRule: timezone projection ---


async def test_window_projects_send_time_into_project_timezone():
    """Pin that the UTC clock face is never compared against local bounds.

    23:30 UTC on 2026-07-15 is 00:30 next day in Europe/London (BST), inside
    a 00:00-06:00 local window. Fails if the rule compares raw UTC times.
    """
    ctx = make_ctx(
        constraint=constraint_with(
            windows=(sms_window(time(0, 0), time(6, 0)),), tz="Europe/London"
        ),
        send_at=datetime(2026, 7, 15, 23, 30, tzinfo=UTC),
        now=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert not decision.allowed


# --- RestrictedWindowsRule: no-constraint paths ---


async def test_window_allows_when_no_delivery_constraint():
    """Pin the self-consistent no-constraints path of the window rule."""
    decision = await RestrictedWindowsRule().evaluate(make_ctx())

    assert decision.allowed


async def test_window_allows_when_constraint_has_no_windows():
    """Pin that a constraint with only blackouts does not reject windows."""
    ctx = make_ctx(constraint=constraint_with())

    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert decision.allowed


# --- BlackoutPeriodRule: membership ---


async def test_blackout_rejects_when_send_date_inside():
    """Pin that a send date within the blackout's inclusive range rejects."""
    ctx = make_ctx(
        constraint=constraint_with(
            blackouts=(blackout(date(2026, 9, 15), date(2026, 9, 17)),)
        )
    )
    decision = await BlackoutPeriodRule().evaluate(ctx)

    assert not decision.allowed
    assert decision.rule == "blackout_period"
    assert "holiday" in decision.reason


async def test_blackout_allows_after_blackout_ends():
    """Pin that a send date after end_date allows."""
    ctx = make_ctx(
        constraint=constraint_with(
            blackouts=(blackout(date(2026, 9, 15), date(2026, 9, 17)),)
        ),
        now=datetime(2026, 9, 18, 9, 0, tzinfo=UTC),
    )
    decision = await BlackoutPeriodRule().evaluate(ctx)

    assert decision.allowed


async def test_blackout_end_date_is_inclusive():
    """Pin that a send on end_date itself is inside the blackout."""
    ctx = make_ctx(
        constraint=constraint_with(
            blackouts=(blackout(date(2026, 9, 15), date(2026, 9, 17)),)
        ),
        now=datetime(2026, 9, 17, 23, 59, tzinfo=UTC),
    )
    decision = await BlackoutPeriodRule().evaluate(ctx)

    assert not decision.allowed


# --- BlackoutPeriodRule: CRITICAL bypass ---


async def test_blackout_bypasses_critical_notifications():
    """Pin that a CRITICAL send during a blackout is never rejected.

    Same grounds as the preference rule's CRITICAL bypass: the recipient's
    need to receive the message (fraud alert, MFA token) outranks the
    project's configured silence. The blackout is the sender's own rule;
    the criticality is about the recipient's need.

    The scenario is judged against ``now`` because the entity forbids
    ``send_at`` on CRITICAL notifications (immediate-only basis) — the
    reachable bypass path is a dispatch moment landing inside a blackout,
    exactly what the guard re-checks.
    """
    ctx = make_ctx(
        constraint=constraint_with(
            blackouts=(blackout(date(2026, 9, 15), date(2026, 9, 17)),)
        ),
        # default now = 2026-09-15 23:00 UTC, inside the blackout range
        category=NotificationCategory.CRITICAL,
    )
    decision = await BlackoutPeriodRule().evaluate(ctx)

    assert decision.allowed


# --- RestrictedWindowsRule: CRITICAL bypass ---


async def test_restricted_window_bypasses_critical_notifications():
    """Pin that a CRITICAL send inside a restricted window is never rejected.

    Same grounds as the blackout and preference bypasses: the recipient's
    need to receive the message outranks the project's configured silence,
    and the bypass is uniform across every time-based rule so a CRITICAL
    dispatch cannot be rejected by one prohibition but not another. The
    window wraps midnight (22:00-06:00) so the pin also exercises the
    wraparound membership check; the judged time is ``now`` because the
    entity forbids ``send_at`` on CRITICAL notifications.
    """
    ctx = make_ctx(
        constraint=constraint_with(windows=(sms_window(time(22, 0), time(6, 0)),)),
        channel=DeliveryChannel.SMS,
        # default now = 2026-09-15 23:00 UTC, inside the wrapped window
        category=NotificationCategory.CRITICAL,
    )
    decision = await RestrictedWindowsRule().evaluate(ctx)

    assert decision.allowed


# --- BlackoutPeriodRule: send-time branch ---


async def test_blackout_send_at_inside_rejects_even_when_ctx_now_outside():
    """Pin that an explicitly scheduled send is judged against its own date."""
    ctx = make_ctx(
        constraint=constraint_with(
            blackouts=(blackout(date(2026, 9, 15), date(2026, 9, 17)),)
        ),
        now=datetime(2026, 9, 18, 9, 0, tzinfo=UTC),  # after blackout
        send_at=datetime(2026, 9, 16, 9, 0, tzinfo=UTC),  # inside blackout
    )
    decision = await BlackoutPeriodRule().evaluate(ctx)

    assert not decision.allowed


# --- BlackoutPeriodRule: timezone projection ---


async def test_blackout_projects_send_date_into_project_timezone():
    """Pin that the UTC calendar date is never compared against local dates.

    23:30 UTC on 2026-09-15 is already 2026-09-16 in Europe/London (BST), so
    a Sep 16-only blackout must reject. Fails if the rule compares UTC dates.
    """
    ctx = make_ctx(
        constraint=constraint_with(
            blackouts=(blackout(date(2026, 9, 16), date(2026, 9, 16)),),
            tz="Europe/London",
        ),
        send_at=datetime(2026, 9, 15, 23, 30, tzinfo=UTC),
        now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )
    decision = await BlackoutPeriodRule().evaluate(ctx)

    assert not decision.allowed


# --- BlackoutPeriodRule: no-constraint paths ---


async def test_blackout_allows_when_no_delivery_constraint():
    """Pin the self-consistent no-constraints path of the blackout rule."""
    decision = await BlackoutPeriodRule().evaluate(make_ctx())

    assert decision.allowed


async def test_blackout_allows_when_constraint_has_no_blackouts():
    """Pin that a constraint with only windows does not reject blackouts."""
    ctx = make_ctx(constraint=constraint_with())
    decision = await BlackoutPeriodRule().evaluate(ctx)

    assert decision.allowed
