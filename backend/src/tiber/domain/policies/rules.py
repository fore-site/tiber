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
        if recipient is None:
            return PolicyDecision.reject("recipient not found", rule=self.name)
        address = recipient.addresses.get(ctx.notification.channel.value)
        if not address:
            return PolicyDecision.reject(
                f"recipient has no {ctx.notification.channel.value} address",
                rule=self.name,
            )
        return PolicyDecision.allow()


class ChannelPreferenceRule:
    """Reject a notification when the recipient opted out of its channel.

    Preferences are read through the ``PreferenceReadModel`` port. Safe
    default: an absent preference is treated as opted-in.
    """

    name = "channel_preference"

    async def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Reject when the recipient has opted out of the notification channel."""
        recipient = ctx.recipient
        if recipient is None:
            return PolicyDecision.reject("recipient not found", rule=self.name)
        channel = ctx.notification.channel
        blocked = await ctx.preferences.blocked_channels(recipient.id)
        if channel in blocked:
            return PolicyDecision.reject(
                f"recipient opted out of {channel.value}",
                rule=self.name,
            )
        return PolicyDecision.allow()
