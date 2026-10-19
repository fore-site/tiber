"""Port for the ML layer.

One call per intake, asking only for the decisions the client left open. The
engine must stay inside ``constraints``; the worker re-checks anyway
(``assemble_plan``), so a misbehaving model cannot produce an invalid plan.
"""

from dataclasses import dataclass
from typing import Protocol

from tiber.domain.entities import Recipient
from tiber.domain.value_objects.intake import (
    DecisionConstraints,
    IntakePayload,
    MlSuggestion,
    Want,
)


@dataclass(frozen=True)
class DecisionRequest:
    """Inputs for one ML decision call."""

    recipient: Recipient
    payload: IntakePayload
    constraints: DecisionConstraints
    want: frozenset[Want]


class DecisionEngine(Protocol):
    """Advisory ML port: one call per intake."""

    async def decide(self, request: DecisionRequest) -> MlSuggestion:
        """Return suggestions for ``request.want``.

        May raise; callers treat any failure or timeout as "no suggestion" and
        fall back to defaults.
        """
        ...
