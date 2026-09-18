"""Delivery-policy decision vocabulary and evaluation.

The engine — vocabulary (``PolicyDecision``, ``PolicyContext``), the rule
contract, the concrete rules, the resolver, and the canonical chains —
lives in ``rules`` as one self-contained module.
"""

from .rules import (
    DISPATCH_GUARD_RULES,
    INTAKE_RULES,
    PolicyContext,
    PolicyDecision,
    PolicyResolver,
    PolicyRule,
)

__all__ = [
    "DISPATCH_GUARD_RULES",
    "INTAKE_RULES",
    "PolicyContext",
    "PolicyDecision",
    "PolicyResolver",
    "PolicyRule",
]
