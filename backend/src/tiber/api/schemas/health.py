from pydantic import BaseModel


class DependencyStatus(BaseModel):
    """Status of running dependencies."""

    database: str = "ok"
    redis: str = "ok"
    rabbitmq: str = "ok"


class HealthResponse(BaseModel):
    """Response model from health endpoint."""

    status: str = "healthy"
    dependencies: DependencyStatus = DependencyStatus()
