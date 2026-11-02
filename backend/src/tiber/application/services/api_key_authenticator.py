"""API key authentication.

Flow for one request
--------------------
1. Reject a key that is not shaped like a Tiber key, before any I/O. This keeps
   garbage out of Redis and the database.
2. Hash it. Only the hash is ever looked up, cached or logged; the raw key is never
   stored. (SHA-256 is appropriate here because keys carry about 256 bits of
   randomness, so there is nothing to brute-force offline.)
3. Get the facts about that hash: from the cache, or on a miss from the repository,
   which are then written to the cache. "No such key" is a fact too, and is cached.
4. Decide, from those facts and the current time, whether the key may be used. This
   one decision is the same whether the facts came from the cache or the database.

The authenticator says who the key is. It does not decide whether that key may act on
a particular project; the caller compares ``principal.project_id`` with the project
being accessed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tiber.application.auth import ApiKeyAuthenticationError, ApiKeyPrincipal
from tiber.application.ports.api_key_auth_cache import ApiKeyAuthCache, CachedApiKey

if TYPE_CHECKING:
    from tiber.domain.repositories import APIKeyRepository

API_KEY_PREFIX = "tb_"

# ``generate_api_key`` produces "tb_" + token_urlsafe(32), which is 43 URL-safe
# characters. The bounds are deliberately loose so changing the key length later does
# not lock every client out, but tight enough to reject junk and oversized input.
_API_KEY_RE = re.compile(r"^tb_[A-Za-z0-9_-]{32,128}$")


def looks_like_api_key(credential: str) -> bool:
    """Cheap test used to choose between API key and token authentication."""
    return credential.startswith(API_KEY_PREFIX)


class ApiKeyAuthenticator:
    """Authenticate raw API keys against the cache and source-of-truth repository."""

    def __init__(
        self,
        *,
        cache: ApiKeyAuthCache,
        repository: APIKeyRepository,
        hash_key: Callable[[str], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Initialize the authenticator with cache, persistence, hashing, and clock ports."""
        self._cache = cache
        self._repository = repository
        self._hash_key = hash_key
        self._clock = clock

    async def authenticate(self, raw_key: str) -> ApiKeyPrincipal:
        """Return the principal for a valid key, or raise ``ApiKeyAuthenticationError``."""
        if not _API_KEY_RE.fullmatch(raw_key):
            raise ApiKeyAuthenticationError("malformed")

        key_hash = self._hash_key(raw_key)
        now = self._clock()

        entry = await self._cache.get(key_hash)
        if entry is None:
            key = await self._repository.get_by_hash(key_hash)
            entry = CachedApiKey.from_key(key) if key else CachedApiKey.not_found()
            await self._cache.set(key_hash, entry)

        return self._evaluate(entry, now)

    @staticmethod
    def _evaluate(entry: CachedApiKey, now: datetime) -> ApiKeyPrincipal:
        if not entry.found:
            raise ApiKeyAuthenticationError("unknown")
        # Revoked is checked before expired: revocation is a deliberate act, and a
        # key that is both should say so.
        if entry.revoked_at is not None:
            raise ApiKeyAuthenticationError("revoked")
        if entry.expires_at is not None and now >= entry.expires_at:
            raise ApiKeyAuthenticationError("expired")

        # Guaranteed by CachedApiKey for any found entry. Keep this as an
        # explicit runtime check because cache data is part of the production
        # execution path and assertions can be disabled with ``python -O``.
        key_id = entry.key_id
        project_id = entry.project_id
        key_prefix = entry.key_prefix
        if key_id is None or project_id is None or key_prefix is None:
            raise RuntimeError("Invalid found API-key cache entry")

        return ApiKeyPrincipal(
            key_id=key_id,
            project_id=project_id,
            key_prefix=key_prefix,
        )
