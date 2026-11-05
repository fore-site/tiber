"""Deterministic fallback for deployments without a configured decision model."""

from tiber.application.ports.decision_engine import DecisionRequest
from tiber.domain.value_objects.intake import MlSuggestion


class FallbackDecisionEngine:
    """Return no suggestions so constrained domain defaults choose the plan."""

    async def decide(self, request: DecisionRequest) -> MlSuggestion:
        """Return an empty suggestion and let plan assembly apply safe defaults."""
        return MlSuggestion()
