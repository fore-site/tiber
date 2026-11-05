from urllib.parse import parse_qs

import httpx
import pytest
import respx

from tiber.application.ports.channel_provider import TransientProviderError
from tiber.core.config import Settings
from tiber.domain.enums import DeliveryChannel
from tiber.domain.value_objects import ContentAction, ContentImage
from tiber.infrastructure.providers.factory import build_provider_manager
from tiber.infrastructure.providers.sms.twilio import TwilioSMSProvider


def test_provider_factory_builds_requested_live_channel_only():
    """Unrelated live provider configuration does not block this channel."""
    settings = Settings.model_construct(
        push_provider="fcm",
        email_provider="resend",
        resend_api_key="re_placeholder",
        email_sender="notifications@example.test",
    )

    manager = build_provider_manager(
        settings,
        channels=(DeliveryChannel.EMAIL,),
    )

    assert type(manager.get(DeliveryChannel.EMAIL)).__name__ == "ResendEmailProvider"


def test_provider_factory_wires_twilio_and_internal_feed():
    """Twilio and the persisted in-app feed are registered by channel."""
    settings = Settings.model_construct(
        sms_provider="twilio",
        twilio_account_sid="AC" + "1" * 32,
        twilio_auth_token="T" * 32,
        twilio_from_number="+15005550006",
    )

    sms_manager = build_provider_manager(
        settings,
        channels=(DeliveryChannel.SMS,),
    )
    in_app_manager = build_provider_manager(
        settings,
        channels=(DeliveryChannel.IN_APP,),
    )

    assert type(sms_manager.get(DeliveryChannel.SMS)).__name__ == "TwilioSMSProvider"
    assert type(in_app_manager.get(DeliveryChannel.IN_APP)).__name__ == "InAppProvider"


@pytest.mark.asyncio
@respx.mock
async def test_twilio_provider_sends_body_and_supported_content_links():
    """Twilio receives the message body and the channel's supported links."""
    route = respx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{'AC' + '1' * 32}/Messages.json"
    ).mock(return_value=httpx.Response(201, json={"sid": "SM123"}))
    provider = TwilioSMSProvider(
        account_sid="AC" + "1" * 32,
        auth_token="T" * 32,
        from_number="+15005550006",
    )

    result = await provider.send(
        recipient_address="+15555550123",
        title=None,
        body="Hello",
        actions=(ContentAction(label="Open", url="https://example.test"),),
        images=(ContentImage(url="https://example.test/image.png"),),
    )

    assert route.called
    fields = parse_qs(route.calls.last.request.content.decode())
    assert fields["To"] == ["+15555550123"]
    assert fields["Body"] == [
        "Hello\n\nOpen: https://example.test\nhttps://example.test/image.png"
    ]
    assert result.success
    assert result.provider_message_id == "SM123"


@pytest.mark.asyncio
@respx.mock
async def test_twilio_transient_http_error_is_retryable():
    """Twilio 5xx responses raise the worker-retryable provider exception."""
    respx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{'AC' + '1' * 32}/Messages.json"
    ).mock(return_value=httpx.Response(503))
    provider = TwilioSMSProvider(
        account_sid="AC" + "1" * 32,
        auth_token="T" * 32,
        from_number="+15005550006",
    )

    with pytest.raises(TransientProviderError):
        await provider.send(
            recipient_address="+15555550123",
            title=None,
            body="Hello",
        )
