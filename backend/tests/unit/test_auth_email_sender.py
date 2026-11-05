from __future__ import annotations

import httpx
import pytest
import respx

from tiber.infrastructure.providers.auth_email import (
    AuthEmailDeliveryError,
    HttpAuthEmailSender,
)


async def test_auth_email_sender_uses_configured_provider() -> None:
    """A configured provider receives the transactional email over HTTPS."""
    sender = HttpAuthEmailSender(
        provider="resend",
        api_key="test-key",
        sender="Tiber <auth@example.com>",
    )

    async with respx.mock as router:
        route = router.post("https://api.resend.com/emails").mock(
            return_value=httpx.Response(status_code=200, json={"id": "mail-1"})
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
