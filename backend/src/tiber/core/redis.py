from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from redis.asyncio import Redis

from tiber.core.config import get_settings

settings = get_settings()

# Connection pool
_pool: aioredis.ConnectionPool | None = None


def get_pool() -> aioredis.ConnectionPool:
    """Return a shared Redis connection pool."""
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            decode_responses=True,
        )
    return _pool


async def close_pool() -> None:
    """Close the shared Redis connection pool."""
    global _pool

    if _pool is not None:
        await _pool.aclose()
        _pool = None


def get_redis_client() -> Redis:
    """Return a Redis client using the shared connection pool.

    Suitable for use outside of FastAPI's dependency system.
    """
    return aioredis.Redis(connection_pool=get_pool())


# FastAPI dependency
async def get_redis() -> AsyncGenerator[Redis]:
    """Yield a Redis client per request.

    Use as: redis: Redis = Depends(get_redis)
    """
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()
