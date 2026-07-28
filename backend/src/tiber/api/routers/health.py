import asyncio
import time
from datetime import UTC, datetime
from typing import Annotated, Literal

import aio_pika
import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.logging import get_logger
from ..dependencies import get_db, get_redis
from ..schemas.health import DependencyStatus, HealthResponse

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter()

HEALTH_TIMEOUT = 2.0
LATENCY_THRESHOLD = 0.5


async def _database_status(
    db: AsyncSession,
) -> Literal["UP", "DEGRADED", "DOWN"]:
    start = time.perf_counter()

    try:
        async with asyncio.timeout(HEALTH_TIMEOUT):
            await db.execute(text("SELECT 1"))

        latency = time.perf_counter() - start

        if latency > LATENCY_THRESHOLD:
            return "DEGRADED"

        return "UP"

    except Exception:
        logger.exception("Database health check failed")
        return "DOWN"


async def _redis_status(
    client: redis.Redis,
) -> Literal["UP", "DEGRADED", "DOWN"]:
    start = time.perf_counter()

    try:
        async with asyncio.timeout(HEALTH_TIMEOUT):
            await client.ping()

        latency = time.perf_counter() - start

        if latency > LATENCY_THRESHOLD:
            return "DEGRADED"

        return "UP"

    except Exception:
        logger.exception("Redis health check failed")
        return "DOWN"


async def _rabbitmq_status() -> Literal["UP", "DEGRADED", "DOWN"]:
    start = time.perf_counter()

    try:
        connection = await asyncio.wait_for(
            aio_pika.connect_robust(settings.rabbitmq_url),
            timeout=HEALTH_TIMEOUT,
        )

        await connection.close()

        latency = time.perf_counter() - start

        if latency > LATENCY_THRESHOLD:
            return "DEGRADED"

        return "UP"

    except Exception:
        logger.exception("RabbitMQ health check failed")
        return "DOWN"


@router.get("/health", response_model=HealthResponse)
async def health_check(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis_client: Annotated[redis.Redis, Depends(get_redis)],
):
    """Check API's health status."""
    database, redis_status, rabbitmq = await asyncio.gather(
        _database_status(db),
        _redis_status(redis_client),
        _rabbitmq_status(),
    )

    return HealthResponse(
        version=settings.app_version,
        checks=DependencyStatus(
            database=database,
            redis=redis_status,
            rabbitmq=rabbitmq,
        ),
        timestamp=datetime.now(UTC),
    )
