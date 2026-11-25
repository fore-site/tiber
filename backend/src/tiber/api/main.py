from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from tiber.api.common.exception_handlers import (
    tiber_error_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from tiber.api.common.metrics import RequestMetricsMiddleware, render_metrics
from tiber.api.docs import register_docs
from tiber.api.v1.routers.health import router as health_router
from tiber.api.versions import VERSIONS
from tiber.core.config import get_settings
from tiber.core.database import engine
from tiber.core.logging import (
    configure_logging,
    get_logger,
    reset_correlation_id,
    set_correlation_id,
)
from tiber.core.telemetry import configure_telemetry
from tiber.domain.exceptions import TiberError

# Configure structlog before the first log call in this process
configure_logging()

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan hook."""
    logger.info("Starting Tiber API service")
    try:
        yield
    finally:
        logger.info("Closing database engine")
        await engine.dispose()

        logger.info("Shutting down Tiber API service")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    configure_telemetry("tiber-api")
    # The framework's own /docs, /redoc and /openapi.json are deliberately off:
    # one generated document would describe every mounted version at once. Each
    # version serves its own curated document instead (see tiber.api.docs).
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    app.add_exception_handler(TiberError, tiber_error_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    if settings.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=settings.cors_allow_methods,
            allow_headers=settings.cors_allow_headers,
        )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        token = set_correlation_id(correlation_id)

        start = time.perf_counter()

        try:
            response: Response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000
            response.headers["X-Correlation-ID"] = correlation_id
            response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"

            return response
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000

            logger.exception(
                "Request failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
            )

            raise
        finally:
            reset_correlation_id(token)

    # Add last so this middleware wraps the request-context middleware and sees
    # every response, including errors.
    app.add_middleware(
        RequestMetricsMiddleware, versions=tuple(version.name for version in VERSIONS)
    )

    # Metrics are intentionally unversioned and unauthenticated: Prometheus
    # scrapes this path over the internal network.
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return render_metrics()

    # Health is intentionally unversioned: infrastructure probes should not
    # need to change when the API version does.
    app.include_router(health_router)

    # Every registered version is mounted side by side, so a breaking change can
    # ship as a new prefix while existing clients keep the prefix they pin.
    for version in VERSIONS:
        app.include_router(version.router, prefix=version.prefix)
        register_docs(app, version, settings)

    return app


app = create_app()
