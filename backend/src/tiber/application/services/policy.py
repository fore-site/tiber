"""Delivery policy resolution and the worker-time dispatch guard.

A ``PolicyResolver`` aggregates ``PolicyRule`` objects (channel opt-outs
first, then address availability) into a single decision. The
``DeliveryPolicyGuard`` is the worker-time re-check invoked just before a
notification is handed to a provider: if a drift-sensitive constraint now
fails, the notification is marked ``policy_rejected`` with a reason instead
of being delivered.
"""

from __future__ import annotations

from collections.abc import Sequence

from tiber.domain.entities import DeliveryConstraint, Notification, Recipient
from tiber.domain.policies import (
    PolicyContext,
    PolicyDecision,
)
from tiber.domain.policies.rules import (
    ChannelPreferenceRule,
    PolicyRule,
    RecipientAddressRule,
)


class PolicyResolver:
    """Evaluate a chain of rules against a notification and recipient."""

    def __init__(
        self,
        rules: Sequence[PolicyRule] | None = None,
    ) -> None:
        """Initialize the resolver with a rule chain.

        Rules run in order; the first rejection short-circuits the chain and
        becomes the overall decision. The default chain checks recipient
        channel opt-outs first, then channel-address availability.
        """
        self._rules = (
            list(rules)
            if rules is not None
            else [RecipientAddressRule(), ChannelPreferenceRule()]
        )

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


class DeliveryPolicyGuard:
    """Worker-time re-check of delivery policies before dispatch."""

    def __init__(self, resolver: PolicyResolver | None = None) -> None:
        """Initialize the guard with a resolver (defaults to a fresh one)."""
        self._resolver = resolver or PolicyResolver()

    async def check(
        self,
        notification: Notification,
        recipient: Recipient,
        delivery_constraint: DeliveryConstraint | None = None,
    ) -> PolicyDecision:
        """Return the policy decision for a notification about to be dispatched."""
        return await self._resolver.evaluate(
            notification, recipient, delivery_constraint
        )
