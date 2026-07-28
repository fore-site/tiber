from datetime import datetime
from typing import Literal

from pydantic import BaseModel, computed_field


class DependencyStatus(BaseModel):
    """Status of running dependencies."""

    database: Literal["UP", "DEGRADED", "DOWN"]
    redis: Literal["UP", "DEGRADED", "DOWN"]
    rabbitmq: Literal["UP", "DEGRADED", "DOWN"]


class HealthResponse(BaseModel):
    """Response model from health endpoint."""

    version: str
    checks: DependencyStatus
    timestamp: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["healthy", "degraded", "unhealthy"]:
        """Dynamically computes overall status based on dependencies."""
        statuses = {self.checks.database, self.checks.redis, self.checks.rabbitmq}

        if "DOWN" in statuses:
            return "unhealthy"
        if "DEGRADED" in statuses:
            return "degraded"
        return "healthy"
