"""Redis-backed, separately named API rate-limit policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pycurb.core import AsyncRateLimiter, LimitRule
from pycurb.core.storage.redis_async import AsyncRedisStorage
from redis.asyncio import Redis

from ...core.config import Settings

RateLimitPolicyName = Literal["auth", "dashboard", "api"]


@dataclass(frozen=True)
class RateLimitPolicy:
    """A named request budget used by one endpoint group."""

    name: RateLimitPolicyName
    limit: int
    window_seconds: int


class RateLimitPolicies:
    """Build the shared engine for independent public, dashboard, and API rules."""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        """Create distinct PyCurb rules while sharing Redis storage."""
        policies = (
            RateLimitPolicy(
                name="auth",
                limit=settings.rate_limit_auth_requests,
                window_seconds=settings.rate_limit_auth_window_seconds,
            ),
            RateLimitPolicy(
                name="dashboard",
                limit=settings.rate_limit_dashboard_requests,
                window_seconds=settings.rate_limit_dashboard_window_seconds,
            ),
            RateLimitPolicy(
                name="api",
                limit=settings.rate_limit_api_requests,
                window_seconds=settings.rate_limit_api_window_seconds,
            ),
        )
        storage = AsyncRedisStorage(
            redis,
            use_redis_time=True,
            fail_open=False,
        )
        self._limiter = AsyncRateLimiter(
            storage=storage,
            rules=[
                LimitRule(
                    name=policy.name,
                    algorithm=settings.rate_limit_algorithm,
                    limit=policy.limit,
                    window=policy.window_seconds,
                )
                for policy in policies
            ],
        )

    @property
    def limiter(self) -> AsyncRateLimiter:
        """Return the limiter consumed by framework adapters."""
        return self._limiter
