"""SendGrid-backed email delivery provider."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

import httpx

from ....application.ports.channel_provider import (
    ProviderResult,
    TransientProviderError,
)
from ....domain.enums import DeliveryChannel

if TYPE_CHECKING:
    from ....domain.value_objects import ContentAction, ContentImage


class SendGridEmailProvider:
    """Email ChannelProvider implementation backed by SendGrid."""

    def __init__(self, *, api_key: str, sender: str) -> None:
        """Configure the provider with its API key and verified sender."""
        if not api_key or not sender:
            raise ValueError("SendGrid API key and email sender are required")
        self._api_key = api_key
        self._sender = sender

    @property
    def name(self) -> str:
        """Return a stable identifier for the provider."""
        return "sendgrid"

    @property
    def channel(self) -> DeliveryChannel:
        """Return the channel supported by this provider."""
        return DeliveryChannel.EMAIL

    async def send(
        self,
        recipient_address: str,
        title: str | None,
        body: str,
        actions: tuple[ContentAction, ...] = (),
        images: tuple[ContentImage, ...] = (),
        metadata: dict | None = None,
    ) -> ProviderResult:
        """Send an email through the SendGrid v3 Mail Send API."""
        if not recipient_address:
            return ProviderResult(
                success=False,
                error_message="recipient address must not be empty",
            )

        payload = {
            "personalizations": [
                {
                    "to": [{"email": recipient_address}],
                    "custom_args": {
                        str(key): str(value) for key, value in (metadata or {}).items()
                    },
                }
            ],
            "from": {"email": self._sender},
            "subject": title or "",
            "content": [
                {"type": "text/plain", "value": body},
                {"type": "text/html", "value": self._build_html(body, actions, images)},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise TransientProviderError("SendGrid request failed") from exc

        if response.status_code in (408, 429) or response.status_code >= 500:
            raise TransientProviderError(
                f"SendGrid returned transient HTTP {response.status_code}"
            )
        if response.is_error:
            return ProviderResult(
                success=False,
                error_message=f"SendGrid returned HTTP {response.status_code}",
            )

        return ProviderResult(
            success=True,
            provider_message_id=response.headers.get("X-Message-Id"),
        )

    async def health_check(self) -> bool:
        """Check that the configured SendGrid credential can access the API."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    "https://api.sendgrid.com/v3/user/profile",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True

    @staticmethod
    def _build_html(
        body: str,
        actions: tuple[ContentAction, ...],
        images: tuple[ContentImage, ...],
    ) -> str:
        """Build a minimal HTML representation of notification content."""
        html = escape(body).replace("\n", "<br>")
        for image in images:
            html += (
                "<p>"
                f'<img src="{escape(image.url, quote=True)}" '
                f'alt="{escape(image.alt or "", quote=True)}" '
                'style="max-width: 100%; height: auto;">'
                "</p>"
            )
        for action in actions:
            html += (
                "<p>"
                f'<a href="{escape(action.url, quote=True)}">'
                f"{escape(action.label)}</a>"
                "</p>"
            )
        return f"<div>{html}</div>"
