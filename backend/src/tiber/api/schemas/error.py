from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard API error response."""

    error: str = Field(
        description="Machine-readable error code.",
        examples=["not_found"],
    )

    message: str = Field(
        description="Human-readable error message.",
        examples=["Notification abc123 not found"],
    )

    status: int = Field(
        description="HTTP status code.",
        examples=[404],
    )

    correlation_id: str = Field(
        description="Correlation identifier used for request tracing.",
    )


class ValidationErrorDetail(BaseModel):
    """Represents a single validation failure."""

    field: str = Field(
        examples=["channel"],
    )

    message: str = Field(
        examples=["Value must be one of email, push, sms, webhook, in_app"],
    )


class ValidationErrorResponse(ErrorResponse):
    """Validation error response."""

    details: list[ValidationErrorDetail]
