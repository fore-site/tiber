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

    Channel-agnostic *meaning*: ``title``/``body`` carry the message,
    ``actions`` the ordered recipient actions (buttons/links), ``images``
    the embedded media. Each channel adapter interprets these per channel
    (links in email, tap target in push, appended URL in SMS, dropped
    where unsupported) - the object itself never renders bytes.
    """

    body: str
    title: str | None = None
    actions: tuple[ContentAction, ...] = field(default=())
    images: tuple[ContentImage, ...] = field(default=())

    def __post_init__(self) -> None:
        """Validate the notification content after initialization."""
        if not self.body or not self.body.strip():
            raise ValueError("Notification content body must not be empty")

        # Accept lists from wire/adapter code, normalize to tuples so the
        # frozen VO stays hashable and genuinely immutable.
        if isinstance(self.actions, list):
            object.__setattr__(self, "actions", tuple(self.actions))
        if isinstance(self.images, list):
            object.__setattr__(self, "images", tuple(self.images))
        for action in self.actions:
            if not isinstance(action, ContentAction):
                raise ValueError("actions must contain ContentAction values")
        for image in self.images:
            if not isinstance(image, ContentImage):
                raise ValueError("images must contain ContentImage values")

    def to_dict(self) -> dict:
        """Serialize to a plain JSON-shaped dict.

        This is both the persistence shape (JSONB ``content`` column) and
        the API wire shape, so every key is always present and the output
        is deterministic.
        """
        return {
            "title": self.title,
            "body": self.body,
            "actions": [{"label": a.label, "url": a.url} for a in self.actions],
            "images": [{"url": i.url, "alt": i.alt} for i in self.images],
        }

    @classmethod
    def from_dict(cls, data: dict) -> NotificationContent:
        """Rebuild content from its JSON-shaped dict form.

        Raises ValueError (not KeyError) on malformed data so corrupt stored
        rows surface as invalid content, not as crashes with unclear origin.
        """
        if not isinstance(data, dict):
            raise ValueError("content must be a JSON object")
        try:
            body = data["body"]
        except KeyError:
            raise ValueError("content is missing required field 'body'") from None
        if not isinstance(body, str):
            raise ValueError("content field 'body' must be a string")

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
            body=body,
            title=title,
            actions=tuple(actions),
            images=tuple(images),
        )
