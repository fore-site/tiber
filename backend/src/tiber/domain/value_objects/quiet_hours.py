from dataclasses import dataclass
from datetime import time

from ..enums import DeliveryChannel


@dataclass(frozen=True)
class QuietHours:
    """Value object representing a restricted delivery time window (quiet hours) for a channel.

    Multiple windows per channel are permitted and composed as OR:
    if any window for the channel matches the current time, delivery is rejected..
    """

    name: str
    window_start: time
    window_end: time
    channel: DeliveryChannel
    description: str | None = None

    def __post_init__(self):
        """Validate the value object's invariants after initialization."""
        # Boundary coercion: raw strings become members, invalid values raise
        # the enum's ValueError, members pass through unchanged.
        object.__setattr__(self, "channel", DeliveryChannel(self.channel.lower()))

        if self.window_start == self.window_end:
            raise ValueError(
                f"Single-instant restriction is not allowed. window_start ({self.window_start}) cannot be equal to window_end ({self.window_end})"
            )
