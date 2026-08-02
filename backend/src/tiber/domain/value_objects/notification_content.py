from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationContent:
    """Value object representing the content of a notification."""

    subject: str | None
    body: str

    def __post_init__(self) -> None:
        """Validate the notification content after initialization."""
        if not self.body or not self.body.strip():
            raise ValueError("Notification content body must not be empty")
