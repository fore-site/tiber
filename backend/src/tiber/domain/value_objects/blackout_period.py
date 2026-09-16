from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BlackoutPeriod:
    """Value object representing date range of silenced notifications."""

    name: str
    start_date: date
    end_date: date

    def __post_init__(self):
        """Validate the value object's invariants after initialization."""
        if self.start_date > self.end_date:
            raise ValueError(
                f"Blackout period start date ({self.start_date}) cannot be after end date ({self.end_date})"
            )
