from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis

from tiber.application.ports.idempotency import IdempotencyGuard
from tiber.core.redis import RedisKeys, RedisTTL


class CachedResponse(BaseModel):
    """Cached HTTP response for an idempotent request.

    Only successful responses should be cached.
    """

    model_config = ConfigDict(frozen=True)

    status_code: int
    response: dict[str, Any]
    created_at: datetime


class IdempotencyStore(IdempotencyGuard):
    """Redis-backed idempotency guard.

    Implements the ``IdempotencyGuard`` application port: stores the mapping
    from an Idempotency-Key to the created notification ID with a 24h TTL
    (``RedisTTL.IDEMPOTENCY``), so duplicate submissions are de-duplicated.

    Also retains a cache-aside response store (``get``/``put``/``delete``)
    for replaying the original HTTP response of a repeated request.
    """

    def __init__(self, redis: Redis) -> None:
        """Accept redis instance."""
        self._redis = redis

    async def check_and_store(
        self,
        project_id: UUID,
        key: str,
        notification_id: UUID,
    ) -> bool:
        """Atomically record an idempotency key -> notification ID mapping.

        Returns True if the key was newly stored (the request may proceed);
        False if the key already exists (a duplicate submission).
        """
        stored = await self._redis.set(
            RedisKeys.idempotency(str(project_id), key),
            str(notification_id),
            ex=RedisTTL.IDEMPOTENCY,
            nx=True,
        )
        return bool(stored)

    async def get_existing_notification_id(
        self, project_id: UUID, key: str
    ) -> UUID | None:
        """Return the notification ID previously stored for this key, if any."""
        value = await self._redis.get(RedisKeys.idempotency(str(project_id), key))

        if value is None:
            return None

        try:
            return UUID(value)
        except ValueError:
            return None

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
            nx=True,
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
