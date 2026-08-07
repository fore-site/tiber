"""Unit tests for the Redis-backed ingestion rate limiter (fixed window)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tiber.core.redis import RedisKeys
from tiber.infrastructure.rate_limit.ingestion_rate_limiter import (
    IngestionRateLimiter,
)


class FakeRedis:
    """Minimal async Redis stand-in implementing the commands the limiter uses."""

    def __init__(self) -> None:
        """Initialize an empty counter store."""
        self._counts: dict[str, int] = {}
        self.expire_ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        """Increment a counter and return its new value (starting at 1)."""
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def get(self, key: str) -> int | None:
        """Return the current counter value, if set."""
        return self._counts.get(key)

    async def expire(self, key: str, ttl: int) -> bool:
        """Record the window TTL applied to a key."""
        self.expire_ttls[key] = ttl
        return True


@pytest.fixture
def limiter() -> tuple[IngestionRateLimiter, FakeRedis]:
    """Return a limiter with a budget of 3 wired to a fake Redis."""
    redis = FakeRedis()
    return (
        IngestionRateLimiter(redis, limit=3, window_seconds=60),
        redis,
    )


async def test_allows_up_to_the_limit(limiter):
    """Requests within the windowed budget are allowed."""
    limiter, _ = limiter
    for _ in range(3):
        assert await limiter.is_allowed(uuid4()) is True


async def test_denies_beyond_the_limit(limiter):
    """Requests beyond the windowed budget are rejected."""
    limiter, _ = limiter
    project_id = uuid4()
    for _ in range(3):
        assert await limiter.is_allowed(project_id) is True
    assert await limiter.is_allowed(project_id) is False
    assert await limiter.is_allowed(project_id) is False


async def test_project_counters_are_isolated(limiter):
    """A busy project does not consume another project's quota."""
    limiter, _ = limiter
    a, b = uuid4(), uuid4()
    for _ in range(3):
        assert await limiter.is_allowed(a) is True
    # b is still at the start of its own window.
    assert await limiter.is_allowed(b) is True


async def test_expiry_is_set_on_first_increment(limiter):
    """The window TTL is applied exactly once, on the first request."""
    limiter, redis = limiter
    project_id = uuid4()
    key = RedisKeys.ingestion_rate_limit(str(project_id))

    assert key not in redis.expire_ttls
    await limiter.is_allowed(project_id)
    await limiter.is_allowed(project_id)

    assert redis.expire_ttls[key] == 60


async def test_remaining_counts_down(limiter):
    """Remaining reports the budget left in the current window."""
    limiter, _ = limiter
    project_id = uuid4()

    assert await limiter.remaining(project_id) == 3
    await limiter.is_allowed(project_id)
    await limiter.is_allowed(project_id)
    assert await limiter.remaining(project_id) == 1


async def test_key_namespace(limiter):
    """The limit key is namespaced under the ingestion rate-limit prefix."""
    project_id = uuid4()
    assert RedisKeys.ingestion_rate_limit(project_id) == (
        f"ratelimit:ingestion:{project_id}"
    )
