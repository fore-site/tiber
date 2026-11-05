"""Transactional email delivery for authentication messages."""

from __future__ import annotations

from typing import Literal

import httpx

from ...application.ports.auth_email_sender import (
    AuthEmailDeliveryError,
)


class HttpAuthEmailSender:
    """Send authentication emails through the configured transactional provider."""

    def __init__(
        self,
        *,
        provider: Literal["mock", "resend"],
        api_key: str,
        sender: str,
    ) -> None:
        """Configure a Resend sender."""
        self._provider = provider
        self._api_key = api_key
        self._sender = sender

    async def send(self, recipient: str, subject: str, body: str) -> None:
        """Send a plain-text message or surface provider/configuration errors."""
        if self._provider == "mock":
            raise AuthEmailDeliveryError(
                "Authentication email delivery is unavailable with EMAIL_PROVIDER=mock."
            )
        if not self._api_key or not self._sender:
            raise AuthEmailDeliveryError(
                "Authentication email delivery requires an API key and EMAIL_SENDER."
            )

        url = "https://api.resend.com/emails"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload = {
            "from": self._sender,
            "to": [recipient],
            "subject": subject,
            "text": body,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AuthEmailDeliveryError(
                f"Authentication email provider {self._provider} failed."
            ) from exc
