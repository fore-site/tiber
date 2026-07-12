import logging
import sys
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

import structlog

from tiber.core.config import get_settings

# Request-scoped correlation ID used throughout the application.
# Other layers may propagate this value to message headers,
# database records, and telemetry as needed.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Retrieve the current correlation ID from the context variable."""
    cid = correlation_id_var.get()
    if not cid:
        # Generate a new correlation ID if not set
        cid = str(uuid4())
        correlation_id_var.set(cid)
    return cid


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID in the context variable."""
    correlation_id_var.set(correlation_id)


# Structlog processor chain
def _add_correlation_id(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    event_dict["correlation_id"] = get_correlation_id()
    return event_dict


def configure_logging() -> None:
    """Configure logging with structlog and standard logging."""
    settings = get_settings()

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _add_correlation_id,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.debug:
        # Human-readable output in development
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # JSON output in production
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            *[
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.DEBUG if settings.debug else logging.INFO)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Retrieve a structlog logger instance for the specified name."""
    return structlog.get_logger(name)
