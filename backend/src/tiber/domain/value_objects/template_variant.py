from dataclasses import dataclass

from ..enums import DeliveryChannel
from ..services import set_enum_attribute, validate_content
from ..value_objects import NotificationContent


@dataclass(frozen=True)
class TemplateVariant:
    """Variant of a reusable notification content tied to a channel.

    Contains a title and body with ``{{variable}}`` placeholders, an optional
    action URL, and an optional image URL.
    """

    channel: DeliveryChannel
    content: NotificationContent

    def __post_init__(self) -> None:
        """Validate the template's state after initialization."""
        set_enum_attribute(self, "channel", DeliveryChannel, self.channel)

        validate_content(self.channel, self.content)
