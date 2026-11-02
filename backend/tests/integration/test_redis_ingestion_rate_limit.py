from __future__ import annotations

from uuid import uuid4

import pytest
from redis.asyncio import Redis

from tiber.core.redis import RedisKeys
from tiber.infrastructure.rate_limit.ingestion_rate_limiter import (
    IngestionRateLimiter,
)


@pytest.mark.asyncio
async def test_ingestion_rate_limit_uses_redis_counters(
    integration_redis: Redis,
) -> None:
    """Requests share a Redis-backed budget per project, not per process."""
    project_id = uuid4()
    key = RedisKeys.ingestion_rate_limit(project_id)
    limiter = IngestionRateLimiter(
        integration_redis,
        limit=2,
        window_seconds=60,
    )

    try:
        results = [
            await limiter.limiter.check(key, limiter.rule_name) for _ in range(3)
        ]
        other_project = await limiter.limiter.check(
            RedisKeys.ingestion_rate_limit(uuid4()),
            limiter.rule_name,
        )
    finally:
        await integration_redis.delete(key)

    assert [result.allowed for result in results] == [True, True, False]
    assert other_project.allowed
