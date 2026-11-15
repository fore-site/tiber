"""HTTP transport that dials a pre-validated webhook address.

Validation and connection must use the same address. If the transport lets HTTPX
resolve the hostname again, a hostile DNS server can answer with a public address
for the policy check and a private one for the POST (DNS rebinding). This
transport therefore rewrites the request URL to the pinned IP and keeps the
original hostname in ``Host`` and in the TLS ``sni_hostname`` extension, so
certificate verification and virtual hosting still see the name.
"""

from __future__ import annotations

import httpx

from ...application.ports.webhook_destination import WebhookDestinationPolicy


class PinnedWebhookTransport(httpx.AsyncBaseTransport):
    """Resolve-then-pin wrapper around another HTTPX transport."""

    def __init__(
        self,
        policy: WebhookDestinationPolicy,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize the transport with its policy and inner transport."""
        self._policy = policy
        self._transport = transport or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Validate the destination, rewrite the URL to its IP, then forward."""
        destination = await self._policy.resolve(str(request.url))

        body = await request.aread()
        headers = request.headers.copy()
        headers["Host"] = destination.host_header

        extensions = dict(request.extensions)
        if destination.sni_hostname is None:
            extensions.pop("sni_hostname", None)
        else:
            extensions["sni_hostname"] = destination.sni_hostname

        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=destination.addresses[0]),
            headers=headers,
            content=body,
            extensions=extensions,
        )
        return await self._transport.handle_async_request(pinned)

    async def aclose(self) -> None:
        """Close the underlying transport."""
        await self._transport.aclose()


def build_webhook_client(
    *,
    policy: WebhookDestinationPolicy,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Build the client used for client callbacks.

    Redirects are disabled: a 30x would let an approved public endpoint bounce
    the POST to an address the policy never saw. Environment proxies are ignored
    for the same reason - a proxy would resolve the destination itself and defeat
    pinning.
    """
    return httpx.AsyncClient(
        transport=PinnedWebhookTransport(policy, transport=transport),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    )
