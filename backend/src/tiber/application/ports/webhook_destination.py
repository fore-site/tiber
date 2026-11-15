"""Port for validating client-supplied webhook destinations.

A webhook URL is tenant-controlled, so "fetch this URL" is an SSRF primitive
until the destination is proven to be public internet space. The port keeps the
decision and the connection separate: a policy resolves a URL to a pinned
destination, and the transport dials exactly that destination.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WebhookDestination:
    """A validated webhook target.

    ``addresses`` are the exact IPs the transport may connect to. ``host``,
    ``host_header`` and ``sni_hostname`` preserve the hostname identity that TLS
    verification and virtual hosting depend on, without letting the transport
    resolve the name again.
    """

    host: str
    port: int
    addresses: tuple[str, ...]
    host_header: str
    sni_hostname: str | None


class WebhookDestinationPolicy(Protocol):
    """Resolve a webhook URL to a destination that is safe to dial."""

    async def resolve(self, url: str) -> WebhookDestination:
        """Return the pinned destination, or raise ``WebhookDestinationError``."""
        ...
