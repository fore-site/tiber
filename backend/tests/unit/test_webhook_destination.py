"""Security pins for client-registered webhook destinations.

The policy must reject private, loopback, link-local, metadata, and transition
addresses both as literals and as DNS answers. The transport must not let HTTPX
re-resolve the hostname after validation.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest

from tiber.application.ports.webhook_destination import WebhookDestination
from tiber.domain.exceptions import WebhookDestinationError
from tiber.infrastructure.webhooks import destination as destination_module
from tiber.infrastructure.webhooks.destination import HttpxWebhookDestinationPolicy
from tiber.infrastructure.webhooks.transport import (
    PinnedWebhookTransport,
    build_webhook_client,
)


def _policy() -> HttpxWebhookDestinationPolicy:
    return HttpxWebhookDestinationPolicy(resolve_timeout_seconds=1.0)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",
        "https://user:secret@example.com/hook",
        "https://example.com/hook#fragment",
        "https://example.com:8443/hook",
        "https://localhost/hook",
        "https://api.localhost/hook",
        "https://printer.local/hook",
        "https://metadata.google.internal/hook",
        "https://service.internal/hook",
        "https://intranet/hook",
        "https://127.0.0.1/hook",
        "https://[::1]/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://0.0.0.0/hook",
        "https://[fc00::1]/hook",
        "https://[fe80::1]/hook",
        "https://[::127.0.0.1]/hook",
        "https://[::10.0.0.1]/hook",
        "https://[::ffff:127.0.0.1]/hook",
        "https://[2002:7f00:1::1]/hook",
        "https://[64:ff9b::7f00:1]/hook",
    ],
)
async def test_rejects_unsafe_url_shapes(url: str) -> None:
    """Private literals and non-HTTPS/non-443 URLs fail before dispatch."""
    with pytest.raises(WebhookDestinationError):
        await _policy().resolve(url)


async def test_accepts_public_https_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """A public host is resolved once and normalized for TLS/Host use."""
    calls: list[tuple[str, int]] = []

    async def fake_resolve(host: str, port: int, timeout: float) -> list[str]:
        calls.append((host, port))
        return ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]

    monkeypatch.setattr(destination_module, "_resolve_addresses", fake_resolve)

    target = await _policy().resolve("https://Example.com./hook?x=1")

    assert calls == [("example.com", 443)]
    assert target.host == "example.com"
    assert target.host_header == "example.com"
    assert target.sni_hostname == "example.com"
    assert target.addresses == (
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    )


async def test_rejects_any_private_dns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mixed public/private answer is hostile, not a routing preference."""

    async def fake_resolve(host: str, port: int, timeout: float) -> list[str]:
        return ["93.184.216.34", "10.0.0.5"]

    monkeypatch.setattr(destination_module, "_resolve_addresses", fake_resolve)

    with pytest.raises(WebhookDestinationError):
        await _policy().resolve("https://example.com/hook")


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "172.16.0.9",
        "192.168.1.10",
        "127.0.0.1",
        "169.254.169.254",
        "100.100.100.200",
        "::1",
        "::127.0.0.1",
        "::10.0.0.1",
        "fd00:ec2::254",
        "fe80::1",
    ],
)
async def test_rejects_non_public_dns_answers(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    """A hostname is rejected if any DNS answer is not public internet space."""

    async def fake_resolve(host: str, port: int, timeout: float) -> list[str]:
        return [address]

    monkeypatch.setattr(destination_module, "_resolve_addresses", fake_resolve)

    with pytest.raises(WebhookDestinationError):
        await _policy().resolve("https://example.com/hook")


async def test_rejects_empty_dns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host that returns no addresses cannot be dispatched to."""

    async def fake_resolve(host: str, port: int, timeout: float) -> list[str]:
        return []

    monkeypatch.setattr(destination_module, "_resolve_addresses", fake_resolve)

    with pytest.raises(WebhookDestinationError):
        await _policy().resolve("https://example.com/hook")


async def test_accepts_public_ip_literal() -> None:
    """A public IP literal is allowed but must not use a hostname for SNI."""
    target = await _policy().resolve("https://93.184.216.34/hook")

    assert target.addresses == ("93.184.216.34",)
    assert target.host_header == "93.184.216.34"
    assert target.sni_hostname is None


@dataclass(frozen=True)
class _StaticPolicy:
    target: WebhookDestination

    async def resolve(self, url: str) -> WebhookDestination:
        return self.target


class _CapturingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.request: httpx.Request | None = None
        self.body: bytes | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.request = request
        self.body = await request.aread()
        return httpx.Response(200, request=request)


async def test_transport_pins_ip_and_preserves_hostname_identity() -> None:
    """The socket target is the validated IP; Host and SNI stay the hostname."""
    capture = _CapturingTransport()
    policy = _StaticPolicy(
        WebhookDestination(
            host="example.com",
            port=443,
            addresses=("93.184.216.34",),
            host_header="example.com",
            sni_hostname="example.com",
        )
    )
    transport = PinnedWebhookTransport(policy, transport=capture)

    async with httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        response = await client.post(
            "https://example.com/hook?token=1",
            content=b"payload",
            headers={"X-Test": "yes"},
        )

    assert response.status_code == 200
    assert capture.request is not None
    assert capture.request.url == "https://93.184.216.34/hook?token=1"
    assert capture.request.headers["Host"] == "example.com"
    assert capture.request.headers["X-Test"] == "yes"
    assert capture.request.extensions["sni_hostname"] == "example.com"
    assert capture.body == b"payload"


async def test_transport_omits_sni_for_ip_destination() -> None:
    """An IP literal is verified as an IP, so no hostname SNI is injected."""
    capture = _CapturingTransport()
    policy = _StaticPolicy(
        WebhookDestination(
            host="93.184.216.34",
            port=443,
            addresses=("93.184.216.34",),
            host_header="93.184.216.34",
            sni_hostname=None,
        )
    )
    transport = PinnedWebhookTransport(policy, transport=capture)

    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        await client.post("https://93.184.216.34/hook", content=b"x")

    assert capture.request is not None
    assert "sni_hostname" not in capture.request.extensions


async def test_client_disables_redirects_and_environment_proxies() -> None:
    """The webhook client cannot be rerouted by redirects or proxy env vars."""
    client = build_webhook_client(
        policy=_StaticPolicy(
            WebhookDestination(
                host="example.com",
                port=443,
                addresses=("93.184.216.34",),
                host_header="example.com",
                sni_hostname="example.com",
            )
        ),
        timeout=1.0,
    )
    try:
        assert client.follow_redirects is False
        assert client.trust_env is False
    finally:
        await client.aclose()
