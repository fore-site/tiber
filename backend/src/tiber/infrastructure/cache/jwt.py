from __future__ import annotations

from datetime import UTC, datetime

from redis.asyncio import Redis

from .keys import RedisKeys
from .ttl import RedisTTL


class JWTBlocklistStore:
    """Redis-backed JWT revocation store.

    This store maintains a blocklist of revoked JWT JTIs (JWT IDs).
    A revoked token remains in Redis until its original expiration time,
    plus a small clock-skew buffer.

    The existence of a key indicates that the token has been revoked.
    No JWT payloads or user information are stored.
    """

    def __init__(self, redis: Redis) -> None:
        """Accept redis instance."""
        self._redis = redis

    async def revoke(
        self,
        *,
        jti: str,
        expires_at: datetime,
    ) -> None:
        """Revoke a JWT.

        Parameters
        ----------
        jti:
            JWT ID claim.

        expires_at:
            Absolute UTC expiry time of the JWT.

        Notes
        -----
        If the token has already expired (taking clock skew into account),
        no Redis entry is created.

        """
        now = datetime.now(UTC)

        ttl = (expires_at - now) + RedisTTL.CLOCK_SKEW

        if ttl.total_seconds() <= 0:
            return

        await self._redis.set(
            RedisKeys.jwt_blocklist(jti),
            "1",
            ex=ttl,
        )

    async def is_revoked(self, *, jti: str) -> bool:
        """Determine whether a JWT has been revoked.

        Parameters
        ----------
        jti:
            JWT ID claim.

        Returns
        -------
        bool
            True if the token has been revoked,
            otherwise False.

        """
        return bool(await self._redis.exists(RedisKeys.jwt_blocklist(jti)))
