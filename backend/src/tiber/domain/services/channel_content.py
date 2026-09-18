"""NotificationContent validation for each channel."""

from __future__ import annotations

from ..enums import DeliveryChannel
from ..exceptions import InvalidNotificationStateError
from ..value_objects import NotificationContent


def validate_content(channel: DeliveryChannel, content: NotificationContent) -> None:
    """Validate if the notification content conforms to the schema for a delivery channel."""
    # validate channel is a valid DeliveryChannel:
    c = DeliveryChannel(channel)

    if c is DeliveryChannel.EMAIL and (not content.title or not content.title.strip()):
        raise InvalidNotificationStateError(
            "Title is required for email delivery channel."
        )
    if c is DeliveryChannel.SMS and content.title:
        raise InvalidNotificationStateError(
            "Title is not allowed for SMS delivery channel."
        )
