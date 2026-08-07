"""Provider selection for delivery channels."""

from __future__ import annotations

from collections.abc import Mapping

from ...application.ports.channel_provider import ChannelProvider
from ...domain.enums import DeliveryChannel
from .mock import MockProvider


class ProviderManager:
    """Select a ``ChannelProvider`` for a delivery channel.

    Live adapters can be registered per channel; any channel without a
    registered adapter falls back to the mock provider. This is where
    failover across multiple providers for one channel will hook in.
    """

    def __init__(
        self,
        registry: Mapping[DeliveryChannel, ChannelProvider] | None = None,
    ) -> None:
        """Initialize the manager with an optional provider registry."""
        self._registry: dict[DeliveryChannel, ChannelProvider] = dict(registry or {})

    def register(self, provider: ChannelProvider) -> None:
        """Register a provider for its channel."""
        self._registry[provider.channel] = provider

    def get(self, channel: DeliveryChannel) -> ChannelProvider:
        """Return the provider to use for a channel (falling back to mock)."""
        provider = self._registry.get(channel)
        if provider is not None:
            return provider
        return MockProvider(channel)
