from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderDomain:
    """Provider-issued state for one sending domain."""

    id: str
    name: str
    status: str
    records: tuple[dict[str, Any], ...]


class SenderDomainProvider(Protocol):
    """Contract for registering and verifying sending domains with a provider."""

    @property
    def name(self) -> str:
        """Return the stable provider identifier."""
        ...

    async def create(self, domain: str) -> ProviderDomain:
        """Register a domain and return the DNS records needed to verify it."""
        ...

    async def verify(self, domain_id: str) -> None:
        """Start the provider's asynchronous verification checks."""
        ...

    async def get(self, domain_id: str) -> ProviderDomain:
        """Retrieve the current provider state for a domain."""
        ...

    async def delete(self, domain_id: str) -> None:
        """Remove a domain from the provider."""
        ...
