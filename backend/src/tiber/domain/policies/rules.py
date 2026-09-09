"""Concrete, side-effect-free delivery policy rules."""

from __future__ import annotations

from typing import Protocol

from . import PolicyContext, PolicyDecision


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
        address = recipient.addresses.get(ctx.notification.channel.value)
        if not address:
            return PolicyDecision.reject(
                f"recipient has no {ctx.notification.channel.value} address",
                rule=self.name,
            )
        return PolicyDecision.allow()


class ChannelPreferenceRule:
    """Reject a notification when the recipient opted out of its channel.

    Opt-outs are read directly from the ``Recipient`` aggregate
    (``opted_out_channels``). Safe default: a recipient with no opt-outs is
    treated as opted-in — silence is never a preference.
    """

    name = "channel_preference"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the recipient has opted out of the notification channel."""
        recipient = ctx.recipient
        channel = ctx.notification.channel
        if channel in recipient.opted_out_channels:
            return PolicyDecision.reject(
                f"recipient opted out of {channel.value}",
                rule=self.name,
            )
        return PolicyDecision.allow()


class BlackoutPeriodRule:
    """Reject a notification when it is sent during a blackout period.

    A blackout period is a time range during which notifications are not
    allowed to be sent. The rule checks if the current time falls within any
    of the defined blackout periods for the recipient.
    """

    name = "blackout_period"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the notification is sent during a blackout period."""
        # Placeholder for actual blackout period logic
        # This would typically involve checking the current time against
        # predefined blackout periods for the recipient or project.
        return PolicyDecision.allow()


class DeliveryWindowsRule:
    """Reject a notification when it is sent outside of delivery windows.

    A delivery window is a time range during which notifications are allowed
    to be sent. The rule checks if the current time falls within any of the
    defined delivery windows for the recipient.
    """

    name = "delivery_windows"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the notification is sent outside of delivery windows."""
        # Placeholder for actual delivery window logic
        # This would typically involve checking the current time against
        # predefined delivery windows for the recipient or project.
        return PolicyDecision.allow()
