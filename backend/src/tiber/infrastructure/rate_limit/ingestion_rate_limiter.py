"""Redis-backed fixed-window rate limiter for notification ingestion."""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis

from ...core.redis import RedisKeys


class IngestionRateLimiter:
    """Fixed-window ingestion limiter keyed per project.

    Each ingestion attempt atomically increments a per-project Redis counter;
    the counter carries a window TTL set on the first increment of each window.
    A request is allowed while the count is within ``limit``.

    Fails closed: a Redis error propagates to the caller (surfacing as a 503
    via the exception handler) rather than silently permitting unbounded
    ingestion.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        limit: int,
        window_seconds: int,
    ) -> None:
        """Initialize the limiter with a Redis client and fixed-window budget."""
        self._redis = redis
        self._limit = limit
        self._window = window_seconds

    async def is_allowed(self, project_id: UUID | str) -> bool:
        """Record one ingestion attempt and report whether it stays within budget.

        Returns ``True`` if the request may proceed, ``False`` if the project has
        exhausted its windowed quota.
        """
        key = RedisKeys.ingestion_rate_limit(str(project_id))
        count = await self._redis.incr(key)
        if count == 1:  # First request in the window establishes its expiry.
            await self._redis.expire(key, self._window)
        return count <= self._limit

    async def remaining(self, project_id: UUID | str) -> int:
        """Return the number of requests still permitted in the current window."""
        key = RedisKeys.ingestion_rate_limit(str(project_id))
        count = await self._redis.get(key)
        used = int(count) if count is not None else 0
        return max(0, self._limit - used)
