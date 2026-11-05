from __future__ import annotations

from typing import Literal

import httpx
import pytest
import respx

from tiber.infrastructure.providers.auth_email import (
    AuthEmailDeliveryError,
    HttpAuthEmailSender,
)


@pytest.mark.parametrize(
    ("provider", "url", "status_code"),
    [
        ("resend", "https://api.resend.com/emails", 200),
        ("sendgrid", "https://api.sendgrid.com/v3/mail/send", 202),
    ],
)
async def test_auth_email_sender_uses_configured_provider(
    provider: Literal["resend", "sendgrid"],
    url: str,
    status_code: int,
) -> None:
    """A configured provider receives the transactional email over HTTPS."""
    sender = HttpAuthEmailSender(
        provider=provider,
        api_key="test-key",
        sender="Tiber <auth@example.com>",
    )

    async with respx.mock as router:
        route = router.post(url).mock(
            return_value=httpx.Response(status_code=status_code, json={"id": "mail-1"})
        )
        await sender.send("user@example.com", "Verify", "Use this link.")

    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"
    assert "user@example.com" in route.calls.last.request.content.decode()


async def test_mock_auth_email_provider_fails_explicitly() -> None:
    """The mock notification provider cannot silently drop security emails."""
    sender = HttpAuthEmailSender(
        provider="mock",
        api_key="",
        sender="",
    )

    with pytest.raises(AuthEmailDeliveryError, match="EMAIL_PROVIDER=mock"):
        await sender.send("user@example.com", "Verify", "Use this link.")
