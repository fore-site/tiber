"""NotificationContent validation for each channel."""

from __future__ import annotations

from ..enums import DeliveryChannel
from ..exceptions import InvalidEntityAttributeError
from ..value_objects import NotificationContent


def validate_content(channel: DeliveryChannel, content: NotificationContent) -> None:
    """Validate if the notification content conforms to the schema for a delivery channel."""
    if (
        content.html_body is not None
        and channel not in (DeliveryChannel.EMAIL, DeliveryChannel.IN_APP)
        and content.plain_text_body is None
    ):
        raise InvalidEntityAttributeError(
            f"HTML-only content is not supported for {channel.value} delivery"
        )
    if channel is DeliveryChannel.EMAIL and (
        not content.title or not content.title.strip()
    ):
        raise InvalidEntityAttributeError(
            "Title is required for email delivery channel."
        )
    if channel is DeliveryChannel.SMS and content.title:
        raise InvalidEntityAttributeError(
            "Title is not allowed for SMS delivery channel."
        )
    if (
        channel not in (DeliveryChannel.EMAIL, DeliveryChannel.IN_APP)
        and content.plain_text_body is None
    ):
        raise InvalidEntityAttributeError(
            f"Plain text content is required for {channel.value} delivery channel."
        )
