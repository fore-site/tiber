from __future__ import annotations

from uuid import UUID


class RedisKeys:
    """All key patterns in one place.

    No key string is ever constructed outside of this class.
    Use the static methods to generate keys with dynamic parts.
    """

    def __new__(cls):
        """Class cannot be instantiated."""
        raise TypeError("RedisKeys cannot be instantiated.")

    @staticmethod
    def jwt_blocklist(jti: str) -> str:
        """Generate a Redis key for a JWT blocklist entry."""
        return f"auth:blocklist:{jti}"

    @staticmethod
    def api_key_revoked(key_hash: str) -> str:
        """Generate a Redis key for a revoked API key."""
        return f"auth:apikey:revoked:{key_hash}"

    @staticmethod
    def refresh_token(token_id: str) -> str:
        """Generate a Redis key for a refresh token."""
        return f"auth:refresh:{token_id}"

    @staticmethod
    def idempotency(project_id: UUID | str, key: str) -> str:
        """Generate a Redis key for an idempotency entry."""
        return f"idempotency:{project_id}:{key}"
