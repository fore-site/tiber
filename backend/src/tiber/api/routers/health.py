import logging
from typing import Annotated

import httpx
import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ..dependencies import get_db, get_redis
from ..schemas.health import HealthResponse

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


@router.get("/health")
async def health_check(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis_client: Annotated[redis.Redis, Depends(get_redis)],
):
    """Check health status of dependencies."""
    health = HealthResponse()

    # Check database
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        health.status = "unhealthy"
        health.dependencies.database = f"error: {e!s}"

    # Check Redis
    try:
        await redis_client.ping()
    except Exception as e:
        health.status = "unhealthy"
        health.dependencies.redis = f"error: {e!s}"

    # RabbitMQ
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "http://rabbitmq:15672/api/overview",
                auth=(settings.rabbitmq_user, settings.rabbitmq_password),
                timeout=5.0,
            )
            if resp.status_code != 200:
                raise Exception(f"RabbitMQ management API returned {resp.status_code}")
    except Exception as e:
        health.status = "unhealthy"
        health.dependencies.rabbitmq = f"error: {e!s}"

    return health
