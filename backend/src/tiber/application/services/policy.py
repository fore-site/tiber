"""Delivery policy resolution and the worker-time dispatch guard.

A ``PolicyResolver`` aggregates ``PolicyRule`` objects (user preferences
first, then address availability) into a single decision. The
``DispatchPolicyGuard`` is the worker-time re-check invoked just before a
notification is handed to a provider: if a drift-sensitive constraint now
fails, the notification is marked ``policy_rejected`` with a reason instead
of being delivered.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from tiber.domain.entities import Notification, Recipient
from tiber.domain.enums import DeliveryChannel
from tiber.domain.policies import (
    PolicyContext,
    PolicyDecision,
    PreferenceReadModel,
)
from tiber.domain.policies.rules import (
    ChannelPreferenceRule,
    PolicyRule,
    RecipientAddressRule,
)


class InMemoryPreferenceReadModel:
    """Minimal in-memory preference read model with permissive defaults.

    Maps a recipient to the set of channels it has opted out of. Recipients
    with no entry default to no blocked channels (opted-in), which is the safe
    default: opt-out is always explicit.
    """

    def __init__(
        self,
        blocked: dict[UUID, frozenset[DeliveryChannel]] | None = None,
    ) -> None:
        """Initialize with an optional recipient -> blocked channels mapping."""
        self._blocked: dict[UUID, frozenset[DeliveryChannel]] = blocked or {}

    async def blocked_channels(self, recipient_id: UUID) -> frozenset[DeliveryChannel]:
        """Return the channels the recipient has blocked (default: none)."""
        return self._blocked.get(recipient_id, frozenset())


class PolicyResolver:
    """Evaluate a chain of rules against a notification and recipient."""

    def __init__(
        self,
        preferences: PreferenceReadModel | None = None,
        rules: Sequence[PolicyRule] | None = None,
    ) -> None:
        """Initialize the resolver with a preference read model and rules.

        Rules run in order; the first rejection short-circuits the chain and
        becomes the overall decision. The default chain checks user
        preferences first, then recipient channel-address availability.
        """
        self._preferences = preferences or InMemoryPreferenceReadModel()
        self._rules = (
            list(rules)
            if rules is not None
            else [ChannelPreferenceRule(), RecipientAddressRule()]
        )

    def build_context(
        self,
        notification: Notification,
        recipient: Recipient | None,
    ) -> PolicyContext:
        """Build the evaluation context for a notification and recipient."""
        return PolicyContext(
            notification=notification,
            recipient=recipient,
            preferences=self._preferences,
        )

    async def evaluate(
        self,
        notification: Notification,
        recipient: Recipient | None,
    ) -> PolicyDecision:
        """Evaluate all rules and return the aggregate decision."""
        ctx = self.build_context(notification, recipient)
        for rule in self._rules:
            decision = await rule.evaluate(ctx)
            if not decision.allowed:
                return decision
        return PolicyDecision.allow()


class DispatchPolicyGuard:
    """Worker-time re-check of delivery policies before dispatch."""

    def __init__(self, resolver: PolicyResolver | None = None) -> None:
        """Initialize the guard with a resolver (defaults to a fresh one)."""
        self._resolver = resolver or PolicyResolver()

    async def check(
        self,
        notification: Notification,
        recipient: Recipient | None,
    ) -> PolicyDecision:
        """Return the policy decision for a notification about to be dispatched."""
        return await self._resolver.evaluate(notification, recipient)
