from dataclasses import dataclass
from datetime import time

from ..enums import DeliveryChannel


@dataclass(frozen=True)
class DeliveryWindow:
    """Value object representing an allowed delivery time window for a channel.

    Multiple windows per channel are permitted and composed as OR:
    if any window for the channel matches the current time, delivery is allowed.
    """

    name: str
    allowed_window_start: time
    allowed_window_end: time
    channel: DeliveryChannel
    description: str | None = None
