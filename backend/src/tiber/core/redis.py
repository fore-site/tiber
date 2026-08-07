from __future__ import annotations

from datetime import timedelta
from uuid import UUID

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


class RedisKeys:
    """All key patterns in one place.

    No key string is ever constructed outside of this class.
    Use the static methods to generate keys with dynamic parts.
    """

    def __new__(cls):
        """Class cannot be instantiated."""
        raise TypeError("RedisKeys cannot be instantiated.")

    @staticmethod
    def jwt_blocklist(jti: str) -> str:
        """Generate a Redis key for a JWT blocklist entry."""
        return f"auth:jwt:blocklist:{jti}"

    @staticmethod
    def api_key(key_hash: str) -> str:
        """Generate a Redis key for an API key auth context."""
        return f"auth:apikey:{key_hash}"

    @staticmethod
    def refresh_token(token: str) -> str:
        """Generate a Redis key for a refresh token."""
        return f"auth:refresh:{token}"

    @staticmethod
    def idempotency(project_id: UUID | str, idempotency_key: str) -> str:
        """Generate a Redis key for an idempotency entry."""
        return f"idempotency:{project_id}:{idempotency_key}"

    @staticmethod
    def ingestion_rate_limit(project_id: UUID | str) -> str:
        """Generate the Redis key for the per-project ingestion rate counter."""
        return f"ratelimit:ingestion:{project_id}"


class RedisTTL:
    """Centralised TTL definitions for Redis keys.

    All durations are expressed as ``timedelta`` objects instead of raw
    integers to improve readability and avoid unit conversion mistakes.

    Dynamic TTLs (e.g. JWT blocklist entries) are computed by the owning
    store rather than defined here.
    """

    def __new__(cls):
        """Class is non-instantiable."""
        raise TypeError("RedisTTL cannot be instantiated.")

    #: Additional time added to JWT expiry when revoking tokens.
    #: Helps tolerate minor clock skew between clients and servers.
    CLOCK_SKEW = timedelta(seconds=30)

    #: Idempotency entries remain valid for 24 hours, matching the API contract.
    IDEMPOTENCY = timedelta(hours=24)

    #: Ingestion rate-limit window (matches the configured window; the counter
    #: is given this TTL on its first increment of each window).
    INGESTION_RATE_LIMIT = timedelta(seconds=60)

    #: Distributed lock duration.
    #: Prevents abandoned locks while giving workers enough time to complete.
    DISTRIBUTED_LOCK = timedelta(seconds=60)

    #: Prediction cache lifetime (reserved for future ML optimisation).
    PREDICTION_CACHE = timedelta(hours=6)

    API_KEY_ACTIVE = timedelta(minutes=5)
    API_KEY_REVOKED = timedelta(days=30)
    API_KEY_NOT_FOUND = timedelta(seconds=60)
