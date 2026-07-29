from __future__ import annotations

from typing import cast

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..core.logging import get_correlation_id, get_logger
from ..domain.exceptions import (
    RateLimitExceededError,
    TiberError,
)
from .schemas.error import (
    ErrorResponse,
    ValidationErrorDetail,
    ValidationErrorResponse,
)

logger = get_logger(__name__)


def error_response(
    *,
    status: int,
    error: str,
    message: str,
) -> JSONResponse:
    """Build standard API error response."""
    payload = ErrorResponse(
        error=error,
        message=message,
        status=status,
        correlation_id=get_correlation_id(),
    )

    return JSONResponse(
        status_code=status,
        content=payload.model_dump(mode="json"),
    )


def validation_error_response(
    *,
    details: list[ValidationErrorDetail],
) -> JSONResponse:
    """Build standard API response for validation."""
    payload = ValidationErrorResponse(
        error="validation_error",
        message="Request validation failed.",
        status=422,
        correlation_id=get_correlation_id(),
        details=details,
    )

    return JSONResponse(
        status_code=422,
        content=payload.model_dump(mode="json"),
    )


async def tiber_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle TiberError and HTTPException errors."""
    if isinstance(exc, TiberError):
        status_code = exc.status_code
        error_code = exc.error_code
        message = str(exc)

        logger.warning(
            "Domain exception caught",
            method=request.method,
            path=request.url.path,
            error_code=error_code,
            status_code=status_code,
        )

    elif isinstance(exc, HTTPException):
        status_code = exc.status_code
        error_code = "http_error"
        message = str(exc.detail)

        logger.warning(
            "HTTP exception",
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            detail=str(exc.detail),
        )

    else:
        # Unexpected exception
        status_code = 500
        error_code = "internal_error"
        message = "An unexpected error occurred."
        logger.warning(
            "Unhandled exception",
            method=request.method,
            path=request.url.path,
            error_code=error_code,
            status_code=status_code,
        )

    response = error_response(
        error=error_code,
        message=message,
        status=status_code,
    )

    if isinstance(exc, RateLimitExceededError) and exc.retry_after is not None:
        response.headers["Retry-After"] = str(exc.retry_after)

    return response


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Override FastAPI's default 422 to match Tiber's OpenAPI ValidationErrorResponse."""
    exc = cast(RequestValidationError, exc)
    details = [
        ValidationErrorDetail(
            field=".".join(
                str(loc) for loc in e["loc"][1:]
            ),  # to get e.g recipient.email hierarchy field
            message=e["msg"],
        )
        for e in exc.errors()
    ]

    response = validation_error_response(details=details)

    return response
