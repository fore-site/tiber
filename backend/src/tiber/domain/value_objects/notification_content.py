from dataclasses import dataclass, field
from urllib.parse import urlparse


def _validate_url(url: str, what: str) -> None:
    """Validate that ``url`` is an absolute http(s) URL."""
    result = urlparse(url.strip())
    if not all([result.scheme in ("http", "https"), result.netloc.strip()]):
        raise ValueError(f"Invalid {what} URL: {url!r}")


@dataclass(frozen=True)
class ContentAction:
    """One recipient action (e.g. a button): visible label plus target URL."""

    label: str
    url: str

    def __post_init__(self) -> None:
        """Validate the action after initialization."""
        if not self.label or not self.label.strip():
            raise ValueError("Content action label must not be empty")
        _validate_url(self.url, "action")


@dataclass(frozen=True)
class ContentImage:
    """One embedded image with optional accessibility text."""

    url: str
    alt: str | None = None

    def __post_init__(self) -> None:
        """Validate the image after initialization."""
        _validate_url(self.url, "image")


@dataclass(frozen=True)
class NotificationContent:
    """Value object representing the content of a notification.

    ``plain_text_body`` and ``html_body`` are alternate or complementary
    representations of the message. ``title`` carries the explicit subject
    for channels that require one; it is never inferred from HTML.
    """

    plain_text_body: str | None = None
    html_body: str | None = None
    title: str | None = None
    actions: tuple[ContentAction, ...] = field(default=())
    images: tuple[ContentImage, ...] = field(default=())

    def __post_init__(self) -> None:
        """Validate the notification content after initialization."""
        if not any(
            value is not None and value.strip()
            for value in (self.plain_text_body, self.html_body)
        ):
            raise ValueError(
                "Notification content needs a non-empty plain_text_body or html_body"
            )
        if self.plain_text_body is not None and not self.plain_text_body.strip():
            raise ValueError("Notification plain_text_body must not be empty")
        if self.html_body is not None and not self.html_body.strip():
            raise ValueError("Notification html_body must not be empty")

    def to_dict(self) -> dict:
        """Serialize to a plain JSON-shaped dict.

        This is both the persistence shape (JSONB ``content`` column) and
        the API wire shape, so every key is always present and the output
        is deterministic.
        """
        return {
            "title": self.title,
            "plain_text_body": self.plain_text_body,
            "html_body": self.html_body,
            "actions": [{"label": a.label, "url": a.url} for a in self.actions],
            "images": [{"url": i.url, "alt": i.alt} for i in self.images],
        }

    @classmethod
    def from_dict(cls, data: dict) -> NotificationContent:
        """Rebuild content from its JSON-shaped dict form."""
        plain_text_body = data.get("plain_text_body", data.get("body"))
        html_body = data.get("html_body")
        if plain_text_body is not None and not isinstance(plain_text_body, str):
            raise ValueError("content field 'plain_text_body' must be a string or null")
        if html_body is not None and not isinstance(html_body, str):
            raise ValueError("content field 'html_body' must be a string or null")

        title = data.get("title")
        if title is not None and not isinstance(title, str):
            raise ValueError("content field 'title' must be a string or null")

        raw_actions = data.get("actions", [])
        raw_images = data.get("images", [])
        if not isinstance(raw_actions, list) or not isinstance(raw_images, list):
            raise ValueError("content fields 'actions'/'images' must be arrays")

        actions = []
        for raw in raw_actions:
            if not isinstance(raw, dict) or "label" not in raw or "url" not in raw:
                raise ValueError("each action requires 'label' and 'url'")
            actions.append(ContentAction(label=raw["label"], url=raw["url"]))

        images = []
        for raw in raw_images:
            if not isinstance(raw, dict) or "url" not in raw:
                raise ValueError("each image requires 'url'")
            images.append(ContentImage(url=raw["url"], alt=raw.get("alt")))

        return cls(
            plain_text_body=plain_text_body,
            html_body=html_body,
            title=title,
            actions=tuple(actions),
            images=tuple(images),
        )
