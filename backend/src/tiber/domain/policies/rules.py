from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

from ..entities import DeliveryConstraint, Notification, Recipient
from ..enums import NotificationCategory
from ..value_objects import QuietHours


@dataclass(frozen=True)
class PolicyDecision:
    """The outcome of evaluating a delivery policy.

    A rejected decision always carries a human-readable ``reason`` so callers
    can surface it as ``policy_violation_reason`` on the notification.
    """

    allowed: bool
    reason: str | None = None
    rule: str | None = None

    @classmethod
    def allow(cls) -> PolicyDecision:
        """Return an allow decision."""
        return cls(allowed=True)

    @classmethod
    def reject(cls, reason: str, rule: str | None = None) -> PolicyDecision:
        """Return a reject decision with a reason."""
        return cls(allowed=False, reason=reason, rule=rule)


@dataclass(frozen=True)
class PolicyContext:
    """Everything a policy rule may inspect to reach a decision."""

    notification: Notification
    recipient: Recipient
    delivery_constraint: DeliveryConstraint | None
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


class PolicyRule(Protocol):
    """Contract for a single policy rule."""

    name: str

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Evaluate the rule against the context and return a decision."""
        ...


class RecipientAddressRule:
    """Reject a notification when the recipient has no address for its channel.

    This is a minimal "based on recipient addresses" guard: a notification
    cannot be delivered to a channel that the recipient has no address for.
    """

    name = "recipient_address"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the recipient has no address for the notification channel."""
        recipient = ctx.recipient
        address = recipient.addresses.get(ctx.notification.channel)
        if not address:
            return PolicyDecision.reject(
                f"recipient has no {ctx.notification.channel} address",
                rule=self.name,
            )
        return PolicyDecision.allow()


class RecipientPreferenceRule:
    """Reject a notification when the notification delivery violates user preference configuration."""

    name = "recipient_preference"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the recipient has unsubscribed from a category of notifications, a topic or a delivery channel.

        CRITICAL notifications bypass this rule entirely: security-relevant
        messages must reach the recipient even on an opted-out channel, so
        the category is consulted before any stored consent state.
        """
        category = ctx.notification.category
        if category is NotificationCategory.CRITICAL:
            return PolicyDecision.allow()

        preferences = ctx.recipient.preferences
        channel = ctx.notification.channel
        topic = ctx.notification.topic_id

        if category in preferences.unsubscribed_categories:
            return PolicyDecision.reject(
                f"recipient unsubscribed from {category.value} notifications",
                rule=self.name,
            )
        if channel in preferences.opted_out_channels:
            return PolicyDecision.reject(
                f"recipient opted out of {channel.value} delivery channel",
                rule=self.name,
            )
        if topic and topic in preferences.unsubscribed_topics:
            return PolicyDecision.reject(
                f"recipient unsubscribed from topic {topic}",
                rule=self.name,
            )
        return PolicyDecision.allow()


class BlackoutPeriodRule:
    """Reject a notification when it is sent during a blackout period.

    A blackout period is a datetime range during which notifications are not
    allowed to be sent. The rule checks if the send instant falls within any
    of the defined blackout periods for the project.

    Because a blackout is now an absolute window in time, no timezone
    projection is performed: an instant is either inside the range or it is
    not, identically in every timezone. Silencing a *local calendar day*
    is the caller's responsibility — they declare the day's boundaries as
    instants in their own timezone.

    A violation is a hard rejection: the notification is never rescheduled
    to after the blackout. The blackout is the client's own configuration,
    so a send that lands inside it contradicts the client's declared rule,
    and Tiber does not silently override client declarations.

    CRITICAL notifications bypass this rule, on the same grounds as the
    preference rule: the recipient's need to receive the message outranks
    the project's configured silence.
    """

    name = "blackout_period"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the notification is sent during a blackout period."""
        if ctx.notification.category is NotificationCategory.CRITICAL:
            return PolicyDecision.allow()

        delivery_constraint = ctx.delivery_constraint
        if not delivery_constraint:
            return PolicyDecision.allow()

        blackout_periods = delivery_constraint.blackout_periods
        if not blackout_periods:
            return PolicyDecision.allow()

        notification = ctx.notification
        send_at = notification.send_at or ctx.now

        for blackout_period in blackout_periods:
            if blackout_period.start <= send_at <= blackout_period.end:
                return PolicyDecision.reject(
                    reason=f"notification cannot be sent within {blackout_period.name} blackout period",
                    rule=self.name,
                )
        return PolicyDecision.allow()


class QuietHoursRule:
    """Reject a notification when it is sent within a quiet-hours window.

    A quiet hours window is a recurring time-of-day range during which
    notifications are not allowed to be sent. The rule checks if the send
    time falls within any of the defined quiet hours for the project.

    CRITICAL notifications bypass this rule, on the same grounds as the
    preference and blackout rules: the recipient's need to receive the
    message outranks the project's configured silence. Keeping the bypass
    uniform across every time-based rule means a CRITICAL dispatch cannot
    be rejected by landing inside one prohibition but not another.
    """

    name = "quiet_hours"

    def _covers(self, window: QuietHours, t: time) -> bool:
        """Check if the given time falls within the restricted window."""
        if window.window_start <= window.window_end:
            return t >= window.window_start and t <= window.window_end
        return t >= window.window_start or t <= window.window_end

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the notification is sent inside the restricted windows."""
        if ctx.notification.category is NotificationCategory.CRITICAL:
            return PolicyDecision.allow()

        notification = ctx.notification
        delivery_constraint = ctx.delivery_constraint
        if not delivery_constraint:
            return PolicyDecision.allow()

        quiet_hours = delivery_constraint.quiet_hours
        project_timezone = ZoneInfo(delivery_constraint.timezone)

        send_time = (
            (notification.send_at or ctx.now).astimezone(project_timezone).time()
        )

        for window in quiet_hours:
            if window.channel == notification.channel and self._covers(
                window, send_time
            ):
                return PolicyDecision.reject(
                    reason=(
                        f"notification cannot be sent within configured restricted window"
                        f" ({window.window_start} - {window.window_end}) for channel {window.channel.value}"
                    ),
                    rule=self.name,
                )
        return PolicyDecision.allow()


class PolicyResolver:
    """Evaluate a chain of rules against a notification and recipient."""

    def __init__(
        self,
        rules: Sequence[PolicyRule] | None = None,
    ) -> None:
        """Initialize the resolver with a rule chain.

        Rules run in order; the first rejection short-circuits the chain and
        becomes the overall decision. The default chain is the documented
        intake order: address availability, then recipient
        preferences, then blackout periods, then quiet hours.
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
        ctx = self.build_context(notification, recipient, delivery_constraint)
        for rule in self._rules:
            decision = await rule.evaluate(ctx)
            if not decision.allowed:
                return decision
        return PolicyDecision.allow()


# Canonical rule chains. The evaluation order is documented business policy
INTAKE_RULES: tuple[PolicyRule, ...] = (
    RecipientAddressRule(),
    RecipientPreferenceRule(),
    BlackoutPeriodRule(),
    QuietHoursRule(),
)
DISPATCH_GUARD_RULES: tuple[PolicyRule, ...] = (
    RecipientPreferenceRule(),
    BlackoutPeriodRule(),
    QuietHoursRule(),
)
