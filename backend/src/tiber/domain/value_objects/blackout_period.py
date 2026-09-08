from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BlackoutPeriod:
    """Value object representing date range of silenced notifications."""

    name: str
    start_date: date
    end_date: date
