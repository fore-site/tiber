from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from ..entities import DeliveryConstraint, Notification, Recipient
from ..enums import PolicyConsequence


@dataclass(frozen=True)
class PolicyDecision:
    """The outcome of evaluating a delivery policy.

    A rejected decision carries the business consequence of the violation
    (``consequence``) — the domain owns the mapping from violation kind to
    what happens next, so application code never string-matches rule names.
    It also always carries a human-readable ``reason`` so the consequence can
    be surfaced with its justification on the notification.
    """

    allowed: bool
    consequence: PolicyConsequence | None = None
    reason: str | None = None
    rule: str | None = None
    # For POSTPONE decisions: the instant after which delivery may proceed.
    resume_at: datetime | None = None

    @classmethod
    def allow(cls) -> PolicyDecision:
        """Return an allow decision."""
        return cls(allowed=True)

    @classmethod
    def reject(
        cls,
        reason: str,
        rule: str,
        *,
        consequence: PolicyConsequence,
        resume_at: datetime | None = None,
    ) -> PolicyDecision:
        """Return a reject decision with its consequence and reason."""
        return cls(
            allowed=False,
            consequence=consequence,
            reason=reason,
            rule=rule,
            resume_at=resume_at,
        )


@dataclass(frozen=True)
class PolicyContext:
    """Everything a delivery policy rule may inspect to reach a decision."""

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
