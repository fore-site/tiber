"""Delivery-policy decision vocabulary and evaluation.

The engine — vocabulary (``PolicyDecision``, ``PolicyContext``), the rule
contract, the concrete rules, the resolver, and the canonical chains —
lives in ``rules`` as one self-contained module. Evaluation order is
documented business policy (doc 03 intake order; doc 04 dispatch re-check
subset), so ``INTAKE_RULES`` and ``DISPATCH_GUARD_RULES`` are domain
constants. The application layer owns only the seams: obtaining the
inputs and acting on the verdict.

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
