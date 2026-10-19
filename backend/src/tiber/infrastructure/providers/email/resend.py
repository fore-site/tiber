"""Resend-backed email delivery provider."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

import resend

from ....application.ports.channel_provider import ProviderResult
from ....domain.enums import DeliveryChannel

if TYPE_CHECKING:
    from ....domain.value_objects import ContentAction, ContentImage


class ResendEmailProvider:
    """Email ChannelProvider implementation backed by Resend."""

    def __init__(
        self,
        *,
        api_key: str,
        sender: str,
    ) -> None:
        """Configure the provider with its API key and verified sender."""
        if not api_key:
            raise ValueError("Resend API key must not be empty")

        if not sender:
            raise ValueError("Email sender must not be empty")

        self._api_key = api_key
        self._sender = sender

    @property
    def name(self) -> str:
        """Return a stable identifier for the provider."""
        return "resend"

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
        """Send an email through Resend."""
        if not recipient_address:
            return ProviderResult(
                success=False,
                error_message="recipient address must not be empty",
            )

        resend.api_key = self._api_key

        params = {
            "from": self._sender,
            "to": [recipient_address],
            "subject": title or "",
            "text": body,
            "html": self._build_html(body, actions, images),
        }

        try:
            response = await resend.Emails.send_async(params)
        except resend.ResendError as exc:
            return ProviderResult(
                success=False,
                error_message=str(exc),
            )
        except Exception as exc:
            return ProviderResult(
                success=False,
                error_message=str(exc),
            )

        provider_message_id = getattr(response, "id", None)

        return ProviderResult(
            success=True,
            provider_message_id=provider_message_id,
        )

    async def health_check(self) -> bool:
        """Check whether the configured Resend credentials are usable."""
        resend.api_key = self._api_key

        try:
            await resend.Domains.list_async()
        except Exception:
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
            image_url = getattr(image, "url", None)

            if not image_url:
                continue

            html += (
                "<p>"
                f'<img src="{escape(str(image_url), quote=True)}" '
                'style="max-width: 100%; height: auto;" alt="">'
                "</p>"
            )

        for action in actions:
            action_url = getattr(action, "url", None)
            action_label = (
                getattr(action, "label", None)
                or getattr(action, "text", None)
                or "Open"
            )

            if not action_url:
                continue

            html += (
                "<p>"
                f'<a href="{escape(str(action_url), quote=True)}">'
                f"{escape(str(action_label))}"
                "</a>"
                "</p>"
            )

        return f"<div>{html}</div>"
