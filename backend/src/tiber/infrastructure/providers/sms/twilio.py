"""Twilio-backed SMS delivery provider."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

from ....application.ports.channel_provider import (
    ProviderResult,
    TransientProviderError,
)
from ....domain.enums import DeliveryChannel

if TYPE_CHECKING:
    from ....domain.value_objects import ContentAction, ContentImage


class TwilioSMSProvider:
    """SMS ChannelProvider implementation backed by Twilio Messaging."""

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
    ) -> None:
        """Configure Twilio account credentials and the sending number."""
        if not account_sid or not auth_token or not from_number:
            raise ValueError(
                "Twilio account SID, auth token, and sender number are required"
            )
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number

    @property
    def name(self) -> str:
        """Return a stable identifier for the provider."""
        return "twilio"

    @property
    def channel(self) -> DeliveryChannel:
        """Return the channel supported by this provider."""
        return DeliveryChannel.SMS

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
        """Send a text message through Twilio's Messages endpoint."""
        if not recipient_address:
            return ProviderResult(
                success=False,
                error_message="recipient phone number must not be empty",
            )

        message = body
        links = [f"{action.label}: {action.url}" for action in actions]
        links.extend(image.url for image in images)
        if links:
            message = f"{message}\n\n" + "\n".join(links)
        endpoint = (
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{quote(self._account_sid, safe='')}/Messages.json"
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    endpoint,
                    auth=(self._account_sid, self._auth_token),
                    data={
                        "To": recipient_address,
                        "From": self._from_number,
                        "Body": message,
                    },
                )
        except httpx.HTTPError as exc:
            raise TransientProviderError("Twilio request failed") from exc

        if response.status_code in (408, 429) or response.status_code >= 500:
            raise TransientProviderError(
                f"Twilio returned transient HTTP {response.status_code}"
            )
        if response.is_error:
            return ProviderResult(
                success=False,
                error_message=f"Twilio returned HTTP {response.status_code}",
            )

        return ProviderResult(
            success=True,
            provider_message_id=response.json().get("sid"),
        )

    async def health_check(self) -> bool:
        """Check that Twilio accepts the configured account credentials."""
        endpoint = (
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{quote(self._account_sid, safe='')}.json"
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    endpoint,
                    auth=(self._account_sid, self._auth_token),
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True
