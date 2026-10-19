"""Firebase Cloud Messaging delivery provider."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import firebase_admin
from firebase_admin import exceptions, messaging

from ....application.ports.channel_provider import ProviderResult
from ....domain.enums import DeliveryChannel

if TYPE_CHECKING:
    from ....domain.value_objects import ContentAction, ContentImage


class FCMProvider:
    """Push ChannelProvider implementation backed by Firebase Cloud Messaging."""

    def __init__(self, *, firebase_app: firebase_admin.App) -> None:
        """Initialize FCM."""
        self._firebase_app = firebase_app

    @property
    def name(self) -> str:
        """Return a stable identifier for the provider."""
        return "fcm"

    @property
    def channel(self) -> DeliveryChannel:
        """Return the channel supported by this provider."""
        return DeliveryChannel.PUSH

    async def send(
        self,
        recipient_address: str,
        title: str | None,
        body: str,
        actions: tuple[ContentAction, ...] = (),
        images: tuple[ContentImage, ...] = (),
        metadata: dict | None = None,
    ) -> ProviderResult:
        """Send a push notification through FCM."""
        if not recipient_address:
            return ProviderResult(
                success=False,
                error_message="recipient address must not be empty",
            )

        data: dict[str, str] = {}

        if metadata:
            data["metadata"] = json.dumps(
                metadata,
                default=str,
            )

        if actions:
            data["actions"] = json.dumps(
                [
                    {
                        "label": (
                            getattr(action, "label", None)
                            or getattr(action, "text", None)
                        ),
                        "url": getattr(action, "url", None),
                    }
                    for action in actions
                ],
                default=str,
            )

        if images:
            data["images"] = json.dumps(
                [
                    getattr(image, "url", None)
                    for image in images
                    if getattr(image, "url", None)
                ],
                default=str,
            )

        image_url = None

        if images:
            image_url = getattr(images[0], "url", None)

        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
                image=image_url,
            ),
            data=data or None,
            fid=recipient_address,
        )

        try:
            response = await messaging.send_each_async(
                [message],
                app=self._firebase_app,
            )
        except (exceptions.FirebaseError, ValueError) as exc:
            return ProviderResult(
                success=False,
                error_message=str(exc),
            )
        except Exception as exc:
            return ProviderResult(
                success=False,
                error_message=str(exc),
            )

        result = response.responses[0]

        if not result.success:
            return ProviderResult(
                success=False,
                error_message=str(result.exception),
            )

        return ProviderResult(
            success=True,
            provider_message_id=result.message_id,
        )

    async def health_check(self) -> bool:
        """Check whether the Firebase application is initialized."""
        try:
            firebase_admin.get_app(self._firebase_app.name)
        except ValueError, exceptions.FirebaseError:
            return False

        return True
