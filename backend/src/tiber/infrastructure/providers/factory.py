"""Build the provider registry from deployment settings."""

from __future__ import annotations

from collections.abc import Collection

import firebase_admin
from firebase_admin import credentials

from ...application.ports.channel_provider import ChannelProvider
from ...core.config import Settings
from ...domain.enums import DeliveryChannel
from .email.resend import ResendEmailProvider
from .in_app import InAppProvider
from .manager import ProviderManager
from .mock import MockProvider
from .push.fcm import FCMProvider
from .sms.twilio import TwilioSMSProvider


def build_provider_manager(
    settings: Settings,
    *,
    channels: Collection[DeliveryChannel] | None = None,
) -> ProviderManager:
    """Create configured providers for the requested channels."""
    selected = set(channels) if channels is not None else set(DeliveryChannel)
    registry: dict[DeliveryChannel, ChannelProvider] = {}
    if DeliveryChannel.EMAIL in selected:
        registry[DeliveryChannel.EMAIL] = _email_provider(settings)
    if DeliveryChannel.PUSH in selected:
        registry[DeliveryChannel.PUSH] = _push_provider(settings)
    if DeliveryChannel.SMS in selected:
        registry[DeliveryChannel.SMS] = _sms_provider(settings)
    if DeliveryChannel.IN_APP in selected:
        registry[DeliveryChannel.IN_APP] = InAppProvider()
    return ProviderManager(registry)


def _email_provider(settings: Settings) -> ChannelProvider:
    if settings.email_provider == "resend":
        return ResendEmailProvider(
            api_key=settings.resend_api_key,
            sender=settings.email_sender,
        )
    return MockProvider(DeliveryChannel.EMAIL)


def _push_provider(settings: Settings) -> ChannelProvider:
    if settings.push_provider == "mock":
        return MockProvider(DeliveryChannel.PUSH)
    if not all(
        (settings.fcm_project_id, settings.fcm_private_key, settings.fcm_client_email)
    ):
        raise ValueError(
            "FCM requires FCM_PROJECT_ID, FCM_PRIVATE_KEY, and FCM_CLIENT_EMAIL"
        )

    app_name = "tiber-notifications"
    try:
        app = firebase_admin.get_app(app_name)
    except ValueError:
        credential = credentials.Certificate(
            {
                "type": "service_account",
                "project_id": settings.fcm_project_id,
                "private_key": settings.fcm_private_key.replace("\\n", "\n"),
                "client_email": settings.fcm_client_email,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        app = firebase_admin.initialize_app(
            credential,
            options={"projectId": settings.fcm_project_id},
            name=app_name,
        )
    return FCMProvider(firebase_app=app)


def _sms_provider(settings: Settings) -> ChannelProvider:
    if settings.sms_provider == "twilio":
        return TwilioSMSProvider(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_from_number,
        )
    return MockProvider(DeliveryChannel.SMS)
