"""Redis-backed rate limiter for notification ingestion, built on pycurb.

Requires ``pip install "pycurb[redis]"``.

pycurb owns the algorithm, the atomic Lua scripts and the key expiry; this module
only supplies the ingestion rule and the failure policy.
"""

from __future__ import annotations

from typing import Literal

from pycurb.core import AsyncRateLimiter, LimitRule
from pycurb.core.storage.redis_async import AsyncRedisStorage
from redis.asyncio import Redis

_RULE_NAME = "ingestion"


class IngestionRateLimiter:
    """Configured ingestion limiter.

    Allows ``limit`` requests per ``window_seconds`` for each adapter key.

    Fails closed: if Redis is unavailable, PyCurb returns a decision marked as
    storage-unavailable instead of silently permitting unbounded ingestion.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        limit: int,
        window_seconds: int,
        algorithm: Literal["fixed_window", "sliding_window"] = "fixed_window",
        use_redis_time: bool = True,
    ) -> None:
        """Initialize the limiter with a Redis client and a per-project budget.

        ``algorithm`` defaults to ``fixed_window``, matching the previous
        behaviour. ``sliding_window`` avoids a project getting up to twice its
        budget across a window boundary, at the cost of more memory per project.

        ``use_redis_time`` makes Redis the single clock, so API instances with
        drifting clocks agree on which window a request belongs to. It costs one
        extra TIME call inside the Lua script (pycurb documents it as under
        0.1 ms). Turn it off for a single-instance deployment.
        """
        storage = AsyncRedisStorage(
            redis,
            use_redis_time=use_redis_time,
            fail_open=False,  # deny, and surface the failure, when Redis is down
        )
        rule = LimitRule(
            name=_RULE_NAME,
            algorithm=algorithm,
            limit=limit,
            window=window_seconds,
        )
        self._limiter = AsyncRateLimiter(storage=storage, rules=[rule])

    @property
    def limiter(self) -> AsyncRateLimiter:
        """Return the configured PyCurb limiter for framework adapters."""
        return self._limiter

    @property
    def rule_name(self) -> str:
        """Return the name of the ingestion rule."""
        return _RULE_NAME
