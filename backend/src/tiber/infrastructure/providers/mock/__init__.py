"""Mock delivery channel adapters.

Drop-in ``ChannelProvider`` implementations used when no live integration is
configured (or in tests). They satisfy the same interface as live adapters and
prove the provider abstraction without external services.
"""

from __future__ import annotations

from uuid import uuid4

from ....application.ports.channel_provider import ProviderResult
from ....domain.enums import DeliveryChannel


class MockProvider:
    """A mock ``ChannelProvider`` for a single channel."""

    def __init__(self, channel: DeliveryChannel, *, fail: bool = False) -> None:
        """Initialize the mock for a channel with an optional forced failure."""
        self._channel = channel
        self._fail = fail

    @property
    def name(self) -> str:
        """Return a stable identifier for the provider."""
        return f"mock_{self._channel.value}"

    @property
    def channel(self) -> DeliveryChannel:
        """Return the channel this provider supports."""
        return self._channel

    async def send(
        self,
        recipient_address: str,
        subject: str | None,
        body: str,
        metadata: dict | None = None,
    ) -> ProviderResult:
        """Simulate a delivery attempt."""
        if self._fail:
            return ProviderResult(
                success=False,
                error_message="mock provider forced failure",
            )
        return ProviderResult(
            success=True,
            provider_message_id=f"mock_{uuid4().hex[:12]}",
        )

    async def health_check(self) -> bool:
        """Return True unless the mock is configured to fail."""
        return not self._fail
