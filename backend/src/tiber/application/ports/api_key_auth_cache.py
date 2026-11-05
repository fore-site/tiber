"""Port for the API key authentication cache.

The cache stores FACTS about a key hash (does it exist, when was it revoked, when
does it expire), never a verdict ("expired", "active"). A verdict depends on the
current time, so a stored one can disagree with the timestamps next to it. Storing
only facts means the same entry is judged against ``now`` on every request, and an
entry that contradicts itself cannot exist.

The database is the source of truth. The cache saves a round trip per request and
also remembers that a key does NOT exist, so repeated bad credentials do not reach
the database.

Contract points that matter for security:

* **Revocation must write through, after it commits.** The revoke use case must
  replace the cached entry (``set`` with the revoked key, or ``invalidate``);
  otherwise a revoked key keeps working until its cached entry expires. Do it after
  the commit: writing first lets a request in the gap reload the still-active row
  and cache it again.
* **A cache failure is never an authentication failure.** Implementations swallow
  their own errors: ``get`` returns ``None`` (a miss) and writes become no-ops, so
  the authenticator falls back to the database.
* **Invalidation is different from ordinary cache use.** A revocation operation
  must observe a failed invalidation and report that revocation state could not be
  confirmed; it must not return success as if a stale active cache entry were gone.
* **Anything unreadable is a miss.** An incomplete or corrupt entry must come back
  as ``None``, never as an answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from tiber.domain.entities import APIKey


@dataclass(frozen=True)
class CachedApiKey:
    """Facts about one key hash.

    ``found=False`` means no such key exists, and carries no other data. For a found
    key, ``revoked_at`` and ``expires_at`` are ``None`` when they do not apply.
    """

    found: bool
    key_id: UUID | None = None
    project_id: UUID | None = None
    key_prefix: str | None = None
    revoked_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        """Check that the entry is self-consistent."""
        identity = (self.key_id, self.project_id, self.key_prefix)
        if self.found:
            if any(value is None for value in identity):
                raise ValueError(
                    "A found entry needs key_id, project_id and key_prefix"
                )
        elif any(
            value is not None for value in (*identity, self.revoked_at, self.expires_at)
        ):
            raise ValueError("A not-found entry carries no data")

        for name in ("revoked_at", "expires_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"`{name}` must be timezone-aware")

    @classmethod
    def not_found(cls) -> CachedApiKey:
        """Return an entry for a key hash that matches no key."""
        return cls(found=False)

    @classmethod
    def from_key(cls, key: APIKey) -> CachedApiKey:
        """Return facts about a stored key, as of now."""
        return cls(
            found=True,
            key_id=key.id,
            project_id=key.project_id,
            key_prefix=key.key_prefix,
            revoked_at=key.revoked_at,
            expires_at=key.expires_at,
        )


class ApiKeyAuthCache(Protocol):
    """A cache of facts about API keys, keyed by the hash of the raw key."""

    async def get(self, key_hash: str) -> CachedApiKey | None:
        """Return the cached entry, or ``None`` on a miss (or a cache failure)."""
        ...

    async def set(self, key_hash: str, entry: CachedApiKey) -> None:
        """Store an entry."""
        ...

    async def invalidate(self, key_hash: str) -> None:
        """Forget a key, for example right after it is created."""
        ...
