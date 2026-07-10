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
# Keep all key patterns here to prevent collisions across components.

class RedisKeys:
    # Auth state
    JWT_BLOCKLIST       = "auth:blocklist:{jti}"           # TTL = token remaining lifetime
    API_KEY_REVOKED     = "auth:revoked:{key_id}"          # TTL = permanent (no expiry)
    REFRESH_TOKEN       = "auth:refresh:{token_id}"        # TTL = refresh_token_expire_days

    # Rate limiting (sliding window)
    RATE_LIMIT          = "ratelimit:{client_id}:{window}"

    # Idempotency
    IDEMPOTENCY         = "idempotency:{project_id}:{key}" # TTL = idempotency_ttl_seconds

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