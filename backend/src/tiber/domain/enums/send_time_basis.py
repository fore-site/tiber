from enum import StrEnum


class SendTimeBasis(StrEnum):
    """Enum values for how `scheduled_at` was determined."""

    IMMEDIATE = "immediate"
    EXPLICIT = "explicit"
    ML_PREDICTED = "ml_predicted"
