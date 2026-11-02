"""Unit tests for the pycurb-backed ingestion rate limiter.

The limiter owns the rule (per project, ``limit`` per ``window_seconds``) and the
failure policy; pycurb owns the counting. These tests pin the policy through a
fake Redis that implements the commands pycurb's fixed-window path uses
(``time``, ``incr``, ``expire``).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pycurb.core.models import RateLimitResult
from redis.exceptions import ConnectionError as RedisConnectionError

from tiber.core.redis import RedisKeys
from tiber.infrastructure.rate_limit.ingestion_rate_limiter import (
    IngestionRateLimiter,
)

WINDOW_SECONDS = 60


class FakeRedis:
    """Minimal async Redis stand-in implementing the commands the limiter uses."""

    def __init__(self) -> None:
        """Initialize an empty counter store."""
        self._counts: dict[str, int] = {}
        self.expire_ttls: dict[str, int] = {}

    async def time(self) -> tuple[int, int]:
        """Return a Redis-style clock reading (seconds, microseconds)."""
        return (1_700_000_000, 0)

    async def incr(self, key: str) -> int:
        """Increment a counter and return its new value (starting at 1)."""
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key: str, ttl: int) -> bool:
        """Record the window TTL applied to a key."""
        self.expire_ttls[key] = ttl
        return True


class BrokenRedis:
    """Redis stand-in whose every command fails the way a dead server does."""

    async def time(self) -> tuple[int, int]:
        """Fail as a refused connection would."""
        raise RedisConnectionError("connection refused")

    async def incr(self, key: str) -> int:
        """Fail as a refused connection would."""
        raise RedisConnectionError("connection refused")

    async def expire(self, key: str, ttl: int) -> bool:
        """Fail as a refused connection would."""
        raise RedisConnectionError("connection refused")


@pytest.fixture
def limiter() -> tuple[IngestionRateLimiter, FakeRedis]:
    """Return a limiter with a budget of 3 wired to a fake Redis."""
    redis = FakeRedis()
    return (
        IngestionRateLimiter(redis, limit=3, window_seconds=WINDOW_SECONDS),
        redis,
    )


async def check(limiter: IngestionRateLimiter, project_id: UUID) -> RateLimitResult:
    """Run the configured PyCurb limiter with the adapter's project key."""
    key = RedisKeys.ingestion_rate_limit(str(project_id))
    return await limiter.limiter.check(key, limiter.rule_name)


async def test_allows_up_to_the_limit(limiter):
    """Requests within the windowed budget are allowed."""
    limiter, _ = limiter
    for _ in range(3):
        assert (await check(limiter, uuid4())).allowed is True


async def test_denies_beyond_the_limit(limiter):
    """Requests beyond the windowed budget are rejected."""
    limiter, _ = limiter
    project_id = uuid4()
    for _ in range(3):
        assert (await check(limiter, project_id)).allowed is True
    assert (await check(limiter, project_id)).allowed is False
    assert (await check(limiter, project_id)).allowed is False


async def test_denial_carries_retry_after(limiter):
    """A denial reports when the window resets, so the API can send Retry-After."""
    limiter, _ = limiter
    project_id = uuid4()
    for _ in range(3):
        await check(limiter, project_id)

    result = await check(limiter, project_id)

    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after is not None
    assert result.retry_after <= WINDOW_SECONDS


async def test_project_counters_are_isolated(limiter):
    """A busy project does not consume another project's quota."""
    limiter, _ = limiter
    a, b = uuid4(), uuid4()
    for _ in range(3):
        assert (await check(limiter, a)).allowed is True
    # b is still at the start of its own window.
    assert (await check(limiter, b)).allowed is True


async def test_expiry_is_set_on_first_increment(limiter):
    """The window TTL is applied exactly once, on the first request."""
    limiter, redis = limiter
    project_id = uuid4()

    assert redis.expire_ttls == {}
    await check(limiter, project_id)
    await check(limiter, project_id)

    # One windowed key, created by the first increment and expired once.
    (key,) = redis.expire_ttls
    assert redis.expire_ttls[key] == WINDOW_SECONDS
    assert str(project_id) in key
    assert "ingestion" in key


async def test_a_dead_redis_fails_closed_with_a_storage_marker():
    """An unavailable store is distinguishable from a quota denial."""
    limiter = IngestionRateLimiter(
        BrokenRedis(), limit=3, window_seconds=WINDOW_SECONDS
    )

    result = await check(limiter, uuid4())

    assert result.allowed is False
    assert result.storage_unavailable is True
