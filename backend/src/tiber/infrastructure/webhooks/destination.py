"""Validation of client-supplied webhook destinations (SSRF defence).

A webhook URL comes from the tenant, not from Tiber, so it is an untrusted
instruction to make an outbound request. The defence has two halves that must
agree on the same address:

1. This policy resolves the hostname **once**, rejects anything outside public
   internet space, and returns the exact IPs it approved.
2. ``tiber.infrastructure.webhooks.transport`` dials one of those IPs while
   keeping the hostname for ``Host`` and TLS SNI, so HTTPX never resolves the
   name again. Without that, DNS rebinding lets the policy see a public answer
   and the POST reach a private address.

Only HTTPS on 443 is accepted. Scheme downgrades, userinfo, fragments and
alternate ports are request-smuggling and redirect surfaces rather than useful
webhook destinations.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from ...application.ports.webhook_destination import WebhookDestination
from ...domain.exceptions import WebhookDestinationError

_ALLOWED_PORT = 443
_BLOCKED_HOSTNAMES = frozenset({"metadata.google.internal"})
_NAT64_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")


def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is unambiguously public internet space.

    ``is_global`` alone misses reserved IPv4-compatible IPv6 addresses such as
    ``::127.0.0.1`` and ``::10.0.0.1``, so every non-public category is checked
    explicitly. IPv4 addresses wrapped inside IPv6 (IPv4-mapped, 6to4, NAT64)
    are unwrapped and judged by the address that will actually be contacted.
    """
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        embedded = address.ipv4_mapped or address.sixtofour
        if embedded is not None:
            return _is_public(embedded)
        if address in _NAT64_PREFIX:
            return _is_public(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return True


def _is_blocked_hostname(host: str) -> bool:
    """Reject names that resolve inside a network even when the answer is public.

    Single-label names ("intranet") and the usual local suffixes are internal
    by definition. The cloud metadata name is blocked explicitly because it is
    the highest-value SSRF target.
    """
    if host in _BLOCKED_HOSTNAMES:
        return True
    if "." not in host:
        return True
    return (
        host.endswith(".localhost")
        or host.endswith(".local")
        or host.endswith(".internal")
    )


def _host_header(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Format an IP literal for an HTTP ``Host`` header."""
    return f"[{address}]" if address.version == 6 else str(address)


async def _resolve_addresses(host: str, port: int, timeout: float) -> list[str]:
    """Resolve ``host`` once, in order, without duplicates.

    Module-level so the policy's tests can pin DNS answers without a network.
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=timeout,
        )
    except (OSError, TimeoutError) as exc:
        raise WebhookDestinationError(
            f"Could not resolve webhook host {host!r}."
        ) from exc
    return list(dict.fromkeys(info[4][0] for info in infos))


class HttpxWebhookDestinationPolicy:
    """Resolve webhook URLs to pinned public destinations."""

    def __init__(self, *, resolve_timeout_seconds: float = 5.0) -> None:
        """Initialize the policy with its DNS timeout."""
        self._resolve_timeout = resolve_timeout_seconds

    async def resolve(self, url: str) -> WebhookDestination:
        """Validate ``url`` and pin the addresses it may be sent to."""
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise WebhookDestinationError("Webhook URL is malformed.") from exc

        if parsed.scheme != "https":
            raise WebhookDestinationError("Webhook URL must use https.")
        if parsed.username is not None or parsed.password is not None:
            raise WebhookDestinationError("Webhook URL must not contain credentials.")
        if parsed.fragment:
            raise WebhookDestinationError("Webhook URL must not contain a fragment.")
        if port is not None and port != _ALLOWED_PORT:
            raise WebhookDestinationError("Webhook URL must use port 443.")

        host = (parsed.hostname or "").rstrip(".").lower()
        if not host:
            raise WebhookDestinationError("Webhook URL has no host.")

        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None

        if literal is not None:
            if not _is_public(literal):
                raise WebhookDestinationError(
                    f"Webhook address {literal} is not public."
                )
            return WebhookDestination(
                host=host,
                port=_ALLOWED_PORT,
                addresses=(str(literal),),
                host_header=_host_header(literal),
                sni_hostname=None,
            )

        if _is_blocked_hostname(host):
            raise WebhookDestinationError(
                f"Webhook host {host!r} is not a public hostname."
            )

        addresses = await _resolve_addresses(host, _ALLOWED_PORT, self._resolve_timeout)
        if not addresses:
            raise WebhookDestinationError(f"Webhook host {host!r} resolved to nothing.")
        for address in addresses:
            try:
                resolved = ipaddress.ip_address(address)
            except ValueError as exc:
                raise WebhookDestinationError(
                    f"Webhook host {host!r} resolved to an invalid address."
                ) from exc
            if not _is_public(resolved):
                # Any private answer makes the whole name untrusted: a round-robin
                # that includes one internal address is an attack, not a routing
                # preference.
                raise WebhookDestinationError(
                    f"Webhook host {host!r} resolves to non-public address {resolved}."
                )

        return WebhookDestination(
            host=host,
            port=_ALLOWED_PORT,
            addresses=tuple(addresses),
            host_header=host,
            sni_hostname=host,
        )
