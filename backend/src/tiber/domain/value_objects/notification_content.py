from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class NotificationContent:
    """Value object representing the content of a notification."""

    body: str
    title: str | None = None
    action_url: str | None = None
    image_url: str | None = None

    def __post_init__(self) -> None:
        """Validate the notification content after initialization."""
        if not self.body or not self.body.strip():
            raise ValueError("Notification content body must not be empty")
        if self.action_url:
            result = urlparse(self.action_url.strip())
            if not all([result.scheme in ("http", "https"), result.netloc.strip()]):
                raise ValueError("Invalid action URL")
        if self.image_url:
            result = urlparse(self.image_url.strip())
            if not all([result.scheme in ("http", "https"), result.netloc.strip()]):
                raise ValueError("Invalid image URL")
