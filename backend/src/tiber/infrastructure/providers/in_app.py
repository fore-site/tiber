"""In-app notification provider backed by the persisted notification feed."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...application.ports.channel_provider import ProviderResult
from ...domain.enums import DeliveryChannel

if TYPE_CHECKING:
    from ...domain.value_objects import ContentAction, ContentImage


class InAppProvider:
    """Treat the persisted in-app notification as the recipient's feed entry."""

    @property
    def name(self) -> str:
        """Return a stable identifier for the provider."""
        return "internal_feed"

    @property
    def channel(self) -> DeliveryChannel:
        """Return the channel supported by this provider."""
        return DeliveryChannel.IN_APP

    async def send(
        self,
        recipient_address: str,
        title: str | None,
        body: str,
        actions: tuple[ContentAction, ...] = (),
        images: tuple[ContentImage, ...] = (),
        metadata: dict | None = None,
        html_body: str | None = None,
    ) -> ProviderResult:
        """Acknowledge the feed entry already persisted by the intake workflow."""
        notification_id = (metadata or {}).get("notification_id")
        return ProviderResult(
            success=True,
            provider_message_id=(
                f"in_app_{notification_id}" if notification_id else "in_app"
            ),
        )

    async def health_check(self) -> bool:
        """Return True because feed delivery uses the application database."""
        return True
