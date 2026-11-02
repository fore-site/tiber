from dataclasses import dataclass

from ..enums import DeliveryChannel
from ..services import validate_content
from ..services.template_variables import content_variables
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
        validate_content(self.channel, self.content)

    @property
    def variables(self) -> frozenset[str]:
        """Names of the ``{{variable}}`` placeholders this variant uses.

        Derived from the content on demand, so it can never go stale.
        """
        return content_variables(self.content)
