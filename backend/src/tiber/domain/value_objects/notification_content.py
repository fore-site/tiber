from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationContent:
    """Value object for Notification content."""

    subject: str | None
    body: str
