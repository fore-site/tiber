"""Delivery policy rules.

Two kinds of time-based constraint live here, and they must not be confused:

- Quiet hours are recurring *wall-clock* ranges, so the send instant is
  projected into the relevant IANA timezone before comparison. Project quiet
  hours use the delivery constraint's timezone; recipient quiet hours use the
  recipient's profile timezone, falling back to UTC when the fact is unknown.
- Blackout periods are absolute datetime ranges, compared as instants. They
  have no wall-clock meaning of their own, so there is nothing to project;
  a projection here would only invite a later comparison on local
  wall-clock times, which the range does not define.

Boundaries are inclusive at both ends (see ``covers``). Zone resolution is
fail-closed by construction: ``Recipient`` and ``DeliveryConstraint`` reject
an unresolvable IANA zone in ``__post_init__``, so a stored zone that tzdata
no longer knows fails the request that loads it instead of quietly evaluating
in the wrong zone.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..entities import DeliveryConstraint, Notification, Recipient
from ..enums import NotificationCategory, PolicyConsequence
from ..value_objects import BlackoutPeriod, QuietHours, RecipientPreferences
from .definitions import PolicyContext, PolicyDecision, PolicyRule

GRACE_MINUTES = 5


def covers(window: QuietHours, t: time) -> bool:
    """Return whether a local wall-clock time falls inside ``window``.

    Both boundaries are inclusive, and a window whose start is later than its
    end spans midnight. The inclusive end is deliberate: a send exactly at
    ``window_end`` is still inside the restriction, so ``next_window_end``
    keeps that same day's occurrence — delivery resumes after the grace
    margin instead of a day later.
    """
    if window.window_start <= window.window_end:
        return window.window_start <= t <= window.window_end
    return t >= window.window_start or t <= window.window_end


def next_window_end(window: QuietHours, after: datetime, tz: ZoneInfo) -> datetime:
    """Return the first instant at or after ``after`` when ``window`` ends.

    The window is a recurring time-of-day range in ``tz``. The next end is
    the next occurrence of ``window.window_end`` on the local wall clock:
    today's end when ``after`` has not passed it, tomorrow's when it has
    (true for both normal and midnight-spanning windows, since a spanning
    window's end on the start's calendar day has already passed whenever the
    start time is behind us — checked, not assumed).

    "Passed" is strict. An ``after`` exactly on the window end is still inside
    the window (see ``covers``), so that same day's end is returned and the
    caller's grace margin resumes delivery minutes later, not a day later.

    A window end inside a DST spring-forward gap has no instant: the wall time
    does not exist, and ``replace`` resolves it with the pre-transition offset,
    which lands up to an hour *after* the declared wall clock. Delivery is
    late, never early — the safe direction for quiet hours.
    """
    local = after.astimezone(tz)
    candidate = local.replace(
        hour=window.window_end.hour,
        minute=window.window_end.minute,
        second=window.window_end.second,
        microsecond=0,
    )
    if candidate < local:
        candidate += timedelta(days=1)
    return candidate


class RecipientAddressRule:
    """Reject a notification when the recipient has no address for its channel.

    This is a minimal "based on recipient addresses" guard: a notification
    cannot be delivered to a channel that the recipient has no address for.
    """

    name = "recipient_address_rule"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the recipient has no address for the notification channel."""
        recipient = ctx.recipient
        address = recipient.addresses.get(ctx.notification.channel)
        if not address:
            return PolicyDecision.reject(
                f"recipient has no {ctx.notification.channel} address",
                self.name,
                consequence=PolicyConsequence.SUPPRESS,
            )
        return PolicyDecision.allow()


class RecipientPreferenceRule:
    """Apply a recipient's stored delivery preferences.

    Consent — unsubscribed categories, opted-out channels, unsubscribed topics —
    suppresses: it is a permanent decision, so postponing would not honour it.
    Time preferences follow the same split as the project's delivery constraint:
    a quiet-hours window postpones the send, a blackout period suppresses it.
    """

    name = "recipient_preference_rule"

    async def _evaluate_blackout_and_quiet_hours(
        self,
        prefs: RecipientPreferences,
        notif: Notification,
        send_time: datetime | None,
        now: datetime,
        tz: str | None,
    ) -> PolicyDecision:
        """Reject a notification that violates the recipient's time preferences.

        The recipient may carry their own quiet hours and blackout period on
        top of the project's delivery constraint. The two restriction kinds
        differ in consequence at both levels:

        - a recipient quiet-hours window postpones (temporary, recurring);
        - a recipient blackout period suppresses (absolute, one-shot).

        Quiet windows are interpreted on the recipient's own wall clock (their
        profile timezone, falling back to UTC when unset) — quiet hours are a
        property of the person being disturbed, not of the sending project.
        """
        preferences = prefs
        notification = notif
        send_at = send_time or now

        if preferences.blackout_period is not None:
            blackout: BlackoutPeriod = preferences.blackout_period
            # Absolute ranges: compared by instant, so the recipient's
            # timezone is irrelevant here and is not consulted.
            if blackout.start <= send_at <= blackout.end:
                return PolicyDecision.reject(
                    reason=(
                        f"recipient blackout period {blackout.name} covers the "
                        f"send time"
                    ),
                    rule=self.name,
                    consequence=PolicyConsequence.SUPPRESS,
                )

        if preferences.quiet_hours is not None:
            window = preferences.quiet_hours
            zone = ZoneInfo(tz) if tz else ZoneInfo("UTC")
            if window.channel == notification.channel and covers(
                window, send_at.astimezone(zone).time()
            ):
                return PolicyDecision.reject(
                    reason=(
                        f"recipient quiet hours ({window.window_start} - "
                        f"{window.window_end}) cover the send time for channel "
                        f"{window.channel.value}"
                    ),
                    rule=self.name,
                    consequence=PolicyConsequence.POSTPONE,
                    resume_at=next_window_end(window, send_at, zone)
                    + timedelta(minutes=GRACE_MINUTES),
                )

        return PolicyDecision.allow()

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the notification violates a stored recipient preference."""
        preferences = ctx.recipient.preferences
        notification = ctx.notification
        channel = ctx.notification.channel
        topic = ctx.notification.topic_id

        if notification.category in preferences.unsubscribed_categories:
            return PolicyDecision.reject(
                f"recipient unsubscribed from "
                f"{notification.category.value} notifications",
                self.name,
                consequence=PolicyConsequence.SUPPRESS,
            )
        if channel in preferences.opted_out_channels:
            return PolicyDecision.reject(
                f"recipient opted out of {channel.value} delivery channel",
                self.name,
                consequence=PolicyConsequence.SUPPRESS,
            )
        if topic and topic in preferences.unsubscribed_topics:
            return PolicyDecision.reject(
                f"recipient unsubscribed from topic {topic}",
                self.name,
                consequence=PolicyConsequence.SUPPRESS,
            )
        return await self._evaluate_blackout_and_quiet_hours(
            preferences,
            notification,
            notification.send_at,
            ctx.now,
            ctx.recipient.timezone,
        )


class ProjectBlackoutPeriodRule:
    """Reject a notification sent during a project blackout period.

    A blackout period is an absolute datetime range during which
    notifications are not allowed to be sent. Because a blackout is an
    absolute window in time, no timezone projection is performed: an instant
    is either inside the range or it is not, identically in every timezone.
    Silencing a *local calendar day* is the caller's responsibility — they
    declare the day's boundaries as instants in their own timezone.

    A violation is a hard rejection: the notification is never rescheduled
    to after the blackout. The blackout is the client's own configuration,
    so a send that lands inside it contradicts the client's declared rule,
    and Tiber does not silently override client declarations.
    """

    name = "blackout_period"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the notification is sent during a blackout period."""
        delivery_constraint = ctx.delivery_constraint
        if not delivery_constraint:
            return PolicyDecision.allow()

        blackout_periods = delivery_constraint.blackout_periods
        if not blackout_periods:
            return PolicyDecision.allow()

        notification = ctx.notification
        send_at = notification.send_at or ctx.now

        for blackout_period in blackout_periods:
            # Absolute ranges: the project timezone has no bearing, and the
            # instants are compared as they are.
            if blackout_period.start <= send_at <= blackout_period.end:
                return PolicyDecision.reject(
                    reason=(
                        f"notification cannot be sent within "
                        f"{blackout_period.name} blackout period"
                    ),
                    rule=self.name,
                    consequence=PolicyConsequence.SUPPRESS,
                )
        return PolicyDecision.allow()


class ProjectQuietHoursRule:
    """Reject a notification sent within a project quiet-hours window.

    A quiet hours window is a recurring time-of-day range during which
    notifications are not allowed to be sent, evaluated on the project's
    configured wall clock. Unlike opt-outs and blackouts, the restriction is
    temporary and recurring: the violation's consequence is postponement,
    with ``resume_at`` computed as the next window end (project timezone)
    plus a small grace margin, so delivery resumes after the window closes
    instead of being dropped or silently retried against the same wall clock.
    """

    name = "quiet_hours"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject (postpone) when the notification is sent inside a window."""
        notification = ctx.notification
        delivery_constraint = ctx.delivery_constraint
        if not delivery_constraint:
            return PolicyDecision.allow()

        quiet_hours = delivery_constraint.quiet_hours
        project_timezone = ZoneInfo(delivery_constraint.timezone)

        send_at = notification.send_at or ctx.now
        send_time = send_at.astimezone(project_timezone).time()

        for window in quiet_hours:
            if window.channel == notification.channel and covers(window, send_time):
                resume_at = next_window_end(
                    window, send_at, project_timezone
                ) + timedelta(minutes=GRACE_MINUTES)
                return PolicyDecision.reject(
                    reason=(
                        "notification cannot be sent within configured restricted "
                        f"window ({window.window_start} - {window.window_end}) "
                        f"for channel {window.channel.value}"
                    ),
                    rule=self.name,
                    consequence=PolicyConsequence.POSTPONE,
                    resume_at=resume_at,
                )
        return PolicyDecision.allow()


class PolicyResolver:
    """Evaluate a chain of rules against a notification and recipient.

    Rules run in order; the first rejection short-circuits the chain and
    becomes the overall decision. CRITICAL notifications bypass the whole
    chain: security-relevant messages must reach the recipient regardless of
    consent or configured silence, and the bypass must be uniform — a
    CRITICAL dispatch can never be rejected by one rule but not another.
    """

    def __init__(
        self,
        rules: Sequence[PolicyRule] | None = None,
    ) -> None:
        """Initialize the resolver with a rule chain.

        Rules run in order; the first rejection short-circuits the chain and
        becomes the overall decision. The default chain is the documented
        intake order: address availability, then recipient preferences, then
        recipient-level restrictions, then project blackout periods, then
        project quiet hours.
        """
        self._rules = list(rules) if rules is not None else list(INTAKE_RULES)

    def build_context(
        self,
        notification: Notification,
        recipient: Recipient,
        delivery_constraint: DeliveryConstraint | None,
    ) -> PolicyContext:
        """Build the evaluation context for a notification and recipient."""
        return PolicyContext(
            notification=notification,
            recipient=recipient,
            delivery_constraint=delivery_constraint,
        )

    async def evaluate(
        self,
        notification: Notification,
        recipient: Recipient,
        delivery_constraint: DeliveryConstraint | None = None,
    ) -> PolicyDecision:
        """Evaluate all rules and return the aggregate decision."""
        if notification.category is NotificationCategory.CRITICAL:
            return PolicyDecision.allow()

        ctx = self.build_context(notification, recipient, delivery_constraint)
        for rule in self._rules:
            decision = await rule.evaluate(ctx)
            if not decision.allowed:
                return decision
        return PolicyDecision.allow()


# Canonical rule chains. The evaluation order is documented business policy.
INTAKE_RULES: tuple[PolicyRule, ...] = (
    RecipientAddressRule(),
    RecipientPreferenceRule(),
    ProjectBlackoutPeriodRule(),
    ProjectQuietHoursRule(),
)
DISPATCH_GUARD_RULES: tuple[PolicyRule, ...] = (
    RecipientPreferenceRule(),
    ProjectBlackoutPeriodRule(),
    ProjectQuietHoursRule(),
)
