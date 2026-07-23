from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis

from .keys import RedisKeys
from .ttl import RedisTTL


class CachedResponse(BaseModel):
    """Cached HTTP response for an idempotent request.

    Only successful responses should be cached.
    """

    model_config = ConfigDict(frozen=True)

    status_code: int
    response: dict[str, Any]
    created_at: datetime


class IdempotencyStore:
    """Redis-backed cache-aside store for idempotent request responses.

    The cache stores successful responses for 24 hours so that repeated
    requests with the same Idempotency-Key return exactly the same HTTP
    response without reprocessing the request.

    PostgreSQL remains the source of truth for notification data.
    """

    def __init__(self, redis: Redis) -> None:
        """Accept redis instance."""
        self._redis = redis

    async def get(
        self,
        *,
        project_id: UUID,
        key: str,
    ) -> CachedResponse | None:
        """Retrieve a cached response.

        Returns
        -------
        CachedResponse
            Cache hit.

        None
            Cache miss.

        """
        value = await self._redis.get(
            RedisKeys.idempotency(
                str(project_id),
                key,
            )
        )

        if value is None:
            return None

        return CachedResponse.model_validate_json(value)

    async def put(
        self,
        *,
        project_id: UUID,
        key: str,
        response: CachedResponse,
    ) -> None:
        """Cache a successful HTTP response."""
        await self._redis.set(
            RedisKeys.idempotency(
                str(project_id),
                key,
            ),
            response.model_dump_json(),
            ex=RedisTTL.IDEMPOTENCY,
        )

    async def delete(
        self,
        *,
        project_id: UUID,
        key: str,
    ) -> None:
        """Remove a cached idempotent response."""
        await self._redis.delete(
            RedisKeys.idempotency(
                str(project_id),
                key,
            )
        )
