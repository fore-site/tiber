from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BlackoutPeriod:
    """Value object representing datetime range of silenced notifications."""

    name: str
    start: datetime
    end: datetime

    def __post_init__(self):
        """Validate the value object's invariants after initialization."""
        if self.start > self.end:
            raise ValueError(
                f"Blackout period start ({self.start.strftime('%Y-%m-%d %H:%M:%S')}) cannot be after end ({self.end.strftime('%Y-%m-%d %H:%M:%S')})"
            )
