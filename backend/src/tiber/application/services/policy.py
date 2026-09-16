"""Worker-time dispatch guard over the domain policy resolver.

Policy evaluation itself is domain logic: ``PolicyResolver`` and the rule
chains live in ``tiber.domain.policies``. This module holds only the
application-side seam — the ``DeliveryPolicyGuard`` the delivery processor
calls just before handing a notification to a provider. The guard uses the
drift-sensitive ``DISPATCH_GUARD_RULES`` subset (preferences, blackout
periods, restricted windows; deliberately no address re-check — see doc
04): if a constraint now fails, the notification is marked
``policy_rejected`` with a reason instead of being delivered.
"""

from __future__ import annotations

from tiber.domain.entities import DeliveryConstraint, Notification, Recipient
from tiber.domain.policies import PolicyDecision
from tiber.domain.policies.rules import DISPATCH_GUARD_RULES, PolicyResolver


class DeliveryPolicyGuard:
    """Worker-time re-check of delivery policies before dispatch.

    Defaults to the drift-sensitive dispatch chain (no address rule), not
    the full intake chain.
    """

    def __init__(self, resolver: PolicyResolver | None = None) -> None:
        """Initialize the guard with a resolver (defaults to the dispatch chain)."""
        self._resolver = resolver or PolicyResolver(rules=DISPATCH_GUARD_RULES)

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
