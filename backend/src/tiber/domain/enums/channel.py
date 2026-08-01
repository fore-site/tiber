from enum import StrEnum


class Channel(StrEnum):
    """Enum values for delivery channels."""

    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    WEBHOOK = "webhook"
    IN_APP = "in_app"
