from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis

from .keys import RedisKeys
from .ttl import RedisTTL


class CachedAPIKey(BaseModel):
    """Cached authentication context for an API key.

    PostgreSQL remains the source of truth.
    Redis stores a cached authentication snapshot.

    found=False represents a cached negative lookup.
    """

    model_config = ConfigDict(frozen=True)

    found: bool
    project_id: UUID | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def not_found(cls) -> CachedAPIKey:
        """Construct a cached negative lookup."""
        return cls(
            found=False,
        )

    @classmethod
    def active(
        cls,
        *,
        project_id: UUID,
        expires_at: datetime | None,
    ) -> CachedAPIKey:
        """Construct a cached active API key."""
        return cls(
            found=True,
            project_id=project_id,
            expires_at=expires_at,
            revoked_at=None,
        )

    @classmethod
    def revoked(
        cls,
        *,
        project_id: UUID,
        expires_at: datetime | None,
        revoked_at: datetime,
    ) -> CachedAPIKey:
        """Construct a cached revoked API key."""
        return cls(
            found=True,
            project_id=project_id,
            expires_at=expires_at,
            revoked_at=revoked_at,
        )


class APIKeyCache:
    """Cache-aside Redis cache for API key authentication.

    Cached states:

    - active API key
    - revoked API key
    - non-existent API key

    PostgreSQL remains the source of truth.
    """

    def __init__(self, redis: Redis) -> None:
        """Accept redis instance."""
        self._redis = redis

    async def get(
        self,
        *,
        key_hash: str,
    ) -> CachedAPIKey | None:
        """Retrieve a cached API key.

        Returns
        -------
        CachedAPIKey
            Cache hit.

        None
            Cache miss.

        """
        value = await self._redis.get(RedisKeys.api_key_revoked(key_hash))

        if value is None:
            return None

        return CachedAPIKey.model_validate_json(value)

    async def put(
        self,
        *,
        key_hash: str,
        entry: CachedAPIKey,
    ) -> None:
        """Cache an API key authentication snapshot."""
        await self._redis.set(
            RedisKeys.api_key_revoked(key_hash),
            entry.model_dump_json(),
            ex=RedisTTL.API_KEY_CACHE,
        )

    async def delete(
        self,
        *,
        key_hash: str,
    ) -> None:
        """Remove an API key from the cache."""
        await self._redis.delete(RedisKeys.api_key_revoked(key_hash))
