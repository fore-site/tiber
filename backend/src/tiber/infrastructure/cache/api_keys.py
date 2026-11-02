"""Redis adapter for the API key authentication cache.

Key and lifetimes come from ``core/redis.py``. The adapter derives the lifetime from
the facts in the entry when it writes:

    not found                      RedisTTL.API_KEY_NOT_FOUND   60 seconds
    revoked                        RedisTTL.API_KEY_REVOKED     30 days
    already expired                RedisTTL.API_KEY_REVOKED     30 days (expiry is permanent)
    usable, with an expiry         min(RedisTTL.API_KEY_ACTIVE, time until expiry)
    usable, no expiry              RedisTTL.API_KEY_ACTIVE      5 minutes

The cache holds the hash and a little metadata, never the raw key. A Redis failure is
never an authentication failure: reads become misses and writes become no-ops, so the
authenticator falls back to the database, which stays the source of truth.

Decoding is strict. Every field is written every time (as ``null`` when it does not
apply) and every field must be present on read. This matters because the cache stores
facts: an entry that lost its ``revoked_at`` would read as "not revoked", so a
damaged or older-format entry must be a miss, never an answer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ...application.ports.api_key_auth_cache import CachedApiKey
from ...core.logging import get_logger
from ...core.redis import RedisKeys, RedisTTL

logger = get_logger(__name__)


class RedisApiKeyAuthCache:
    """Satisfies the ``ApiKeyAuthCache`` protocol structurally."""

    def __init__(self, redis: Redis) -> None:
        """Initialize the cache with a Redis client."""
        self._redis = redis

    async def get(self, key_hash: str) -> CachedApiKey | None:
        """Return a cached authentication fact, or ``None`` on a miss or Redis error."""
        try:
            raw = await self._redis.get(RedisKeys.api_key(key_hash))
        except RedisError as exc:
            logger.warning(
                "API key cache read failed; using the database", error=str(exc)
            )
            return None
        if raw is None:
            return None
        try:
            return self._decode(json.loads(raw))
        except ValueError, KeyError, TypeError:
            # Corrupt, incomplete or older-format: a miss, never an answer.
            logger.warning("Discarding an unreadable API key cache entry")
            return None

    async def set(self, key_hash: str, entry: CachedApiKey) -> None:
        """Write an authentication fact with a state-appropriate lifetime."""
        ttl = self._ttl(entry, datetime.now(UTC))
        try:
            await self._redis.set(
                RedisKeys.api_key(key_hash),
                json.dumps(self._encode(entry)),
                ex=max(1, int(ttl.total_seconds())),
            )
        except RedisError as exc:
            logger.warning("API key cache write failed", error=str(exc))

    async def invalidate(self, key_hash: str) -> None:
        """Remove a cached authentication fact when invalidation is requested."""
        try:
            await self._redis.delete(RedisKeys.api_key(key_hash))
        except RedisError as exc:
            logger.warning("API key cache invalidation failed", error=str(exc))

    @staticmethod
    def _ttl(entry: CachedApiKey, now: datetime) -> timedelta:
        if not entry.found:
            return RedisTTL.API_KEY_NOT_FOUND
        if entry.revoked_at is not None:
            return RedisTTL.API_KEY_REVOKED
        if entry.expires_at is None:
            return RedisTTL.API_KEY_ACTIVE
        remaining = entry.expires_at - now
        if remaining <= timedelta(0):
            return RedisTTL.API_KEY_REVOKED  # already expired, and that never reverses
        # Never keep a key cached as usable past the moment it expires.
        return min(RedisTTL.API_KEY_ACTIVE, remaining)

    @staticmethod
    def _encode(entry: CachedApiKey) -> dict[str, Any]:
        return {
            "found": entry.found,
            "key_id": str(entry.key_id) if entry.key_id else None,
            "project_id": str(entry.project_id) if entry.project_id else None,
            "key_prefix": entry.key_prefix,
            "revoked_at": entry.revoked_at.isoformat() if entry.revoked_at else None,
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
        }

    @staticmethod
    def _decode(data: dict[str, Any]) -> CachedApiKey:
        found = data["found"]
        if not isinstance(found, bool):
            raise ValueError("`found` must be a boolean")
        key_prefix = data["key_prefix"]
        if key_prefix is not None and not isinstance(key_prefix, str):
            raise ValueError("`key_prefix` must be a string")

        def uuid_or_none(value: str | None) -> UUID | None:
            return None if value is None else UUID(value)

        def datetime_or_none(value: str | None) -> datetime | None:
            return None if value is None else datetime.fromisoformat(value)

        # Indexing (not .get) means a missing field raises KeyError, which is a miss.
        return CachedApiKey(
            found=found,
            key_id=uuid_or_none(data["key_id"]),
            project_id=uuid_or_none(data["project_id"]),
            key_prefix=key_prefix,
            revoked_at=datetime_or_none(data["revoked_at"]),
            expires_at=datetime_or_none(data["expires_at"]),
        )
