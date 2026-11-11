from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.logging import get_correlation_id, get_logger
from ..domain.exceptions import TiberError
from .schemas.error import (
    ErrorResponse,
    ValidationErrorDetail,
    ValidationErrorResponse,
)

logger = get_logger(__name__)

_TIBER_ERROR_STATUS: dict[str, int] = {
    "not_found_error": 404,
    "invalid_entity_attribute": 422,
    "invalid_state_transition": 409,
    "idempotency_key_conflict": 409,
    "name_conflict": 409,
    "project_scope_violated": 403,
    "channel_not_available": 422,
    "template_channel_mismatch": 422,
    "delivery_failed": 502,
    "provider_unavailable": 503,
    "rate_limiter_unavailable": 503,
}


def error_response(
    *,
    status: int,
    error: str,
    message: str,
    headers: Mapping[str, str] | None = None,
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
        headers=headers,
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


async def tiber_error_exception_handler(
    request: Request, exc: TiberError
) -> JSONResponse:
    """Handle TiberError errors."""
    status_code = _TIBER_ERROR_STATUS.get(exc.error_code, 500)
    error_code = exc.error_code
    message = str(exc)

    logger.warning(
        "Domain exception caught",
        method=request.method,
        path=request.url.path,
        error_code=error_code,
        status_code=status_code,
    )

    return error_response(
        error=error_code,
        message=message,
        status=status_code,
        headers=None,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle HTTPException errors."""
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

    return error_response(
        error=error_code,
        message=message,
        status=status_code,
        headers=exc.headers,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors."""
    status_code = 500
    error_code = "internal_error"
    message = "An unexpected error occurred."

    logger.warning(
        "Unhandled exception",
        method=request.method,
        path=request.url.path,
        error_code=error_code,
        status_code=status_code,
        detail=str(exc),
    )

    return error_response(
        error=error_code,
        message=message,
        status=status_code,
        headers=None,
    )


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
