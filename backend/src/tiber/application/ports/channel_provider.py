from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...domain.enums import DeliveryChannel


@dataclass(frozen=True)
class ProviderResult:
    """Represents the result of a delivery attempt by a provider.

    Attributes:
        success (bool): Indicates whether the delivery was successful.
        provider_message_id (str, optional): The ID of the message as provided by the delivery provider.
        error_message (str, optional): An optional error message if the delivery failed.

    """

    success: bool
    provider_message_id: str | None = None
    error_message: str | None = None


# Channel Provider port


class ChannelProvider(Protocol):
    """Contract for delivery channel adapters (email, push, SMS, etc.).

    Each adapter implements exactly one channel.
    Retry and failover decision belong to the caller (Provider Manager), not to the adapter itself.
    """

    @property
    def channel(self) -> DeliveryChannel:
        """Return the delivery channel this provider supports.

        Returns:
            DeliveryChannel: The delivery channel supported by this provider.

        """
        ...

    async def send(
        self,
        recipient_address: str,
        subject: str | None,
        body: str,
        metadata: dict | None = None,
    ) -> ProviderResult:
        """Send a message to the specified recipient address.

        Args:
            recipient_address (str): The address of the recipient.
            subject (str | None): The subject of the message (optional).
            body (str): The body of the message.
            metadata (dict | None): Optional metadata for the message.

        Returns:
            ProviderResult: The result of the delivery attempt.

        """
        ...

    async def health_check(self) -> bool:
        """Perform a health check on the provider.

        Returns:
            bool: True if the provider is healthy, False otherwise.

        """
        ...
