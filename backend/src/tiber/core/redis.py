from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from redis.asyncio import Redis

from tiber.core.config import get_settings

settings = get_settings()

# Connection pool
_pool: aioredis.ConnectionPool | None = None


def get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            decode_responses=True,
        )
    return _pool


def get_redis_client() -> Redis:
    """
    Return a Redis client using the shared connection pool.
    Suitable for use outside of FastAPI's dependency system.
    """
    return aioredis.Redis(connection_pool=get_pool())


# FastAPI dependency
async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    Yield a Redis client per request.
    Use as: redis: Redis = Depends(get_redis)
    """
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


# Redis key namespaces

class RedisKeys:
    """
    All key patterns in one place.
    No key string is ever constructed outside of this class.
    Use the static methods to generate keys with dynamic parts.
    """

    @staticmethod
    def jwt_blocklist(jti: str) -> str:
        return f"auth:blocklist:{jti}"

    @staticmethod
    def api_key_revoked(key_id: str) -> str:
        return f"auth:revoked:{key_id}"

    @staticmethod
    def refresh_token(token_id: str) -> str:
        return f"auth:refresh:{token_id}"

    @staticmethod
    def rate_limit(client_id: str, window: int) -> str:
        return f"ratelimit:{client_id}:{window}"

    @staticmethod
    def idempotency(project_id: str, key: str) -> str:
        return f"idempotency:{project_id}:{key}"