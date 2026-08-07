"""Domain-safe policy primitives.

This package defines the vocabulary for delivery-policy decisions without
binding them to any storage or framework: a decision, the context a rule
evaluates against, the rule contract, and a port for reading recipient
preferences. The concrete rules live in ``.rules`` and the orchestration
(resolver / worker-time guard) lives in the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from ..entities import Notification, Recipient
from ..enums import DeliveryChannel


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
    recipient: Recipient | None
    preferences: PreferenceReadModel
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


class PreferenceReadModel(Protocol):
    """Port for reading recipient delivery preferences.

    ``blocked_channels`` returns the set of channels the recipient has
    explicitly opted out of. A missing entry (no stored preference) must be
    reported as an empty set — the safe, permissive default — so that opt-out
    is always an explicit decision and never silence.
    """

    async def blocked_channels(self, recipient_id: UUID) -> frozenset[DeliveryChannel]:
        """Return the channels the recipient has blocked."""
        ...
