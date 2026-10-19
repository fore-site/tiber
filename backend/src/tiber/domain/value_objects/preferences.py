from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from ..enums import DeliveryChannel, NotificationCategory

if TYPE_CHECKING:
    from ..entities import NotificationTopic
    from .blackout_period import BlackoutPeriod
    from .quiet_hours import QuietHours


@dataclass(frozen=True)
class RecipientPreferences:
    """Value object holding a recipient's consent state."""

    opted_out_channels: frozenset[DeliveryChannel] = field(default_factory=frozenset)
    unsubscribed_categories: frozenset[NotificationCategory] = field(
        default_factory=frozenset
    )
    unsubscribed_topics: frozenset[UUID] = field(default_factory=frozenset)
    blackout_period: BlackoutPeriod | None = None
    quiet_hours: QuietHours | None = None

    def __post_init__(self) -> None:
        """Normalize inputs and enforce a CRITICAL-unstorable invariant."""
        # Callers may pass lists (JSON, tests); the field contract is a frozenset,
        # so normalize here rather than letting equality and hashing depend on
        # whatever sequence the caller happened to use.
        for name in (
            "opted_out_channels",
            "unsubscribed_categories",
            "unsubscribed_topics",
        ):
            object.__setattr__(self, name, frozenset(getattr(self, name)))

        if NotificationCategory.CRITICAL in self.unsubscribed_categories:
            raise ValueError(
                "CRITICAL notifications are always deliverable and cannot "
                "be unsubscribed from"
            )

    def is_subscribed(self, category: NotificationCategory) -> bool:
        """Return whether the recipient receives this notification category.

        CRITICAL is implicitly always subscribed and never consults the
        stored sets: the implicit-yes for category-level consent lives here
        and nowhere else.
        """
        if category is NotificationCategory.CRITICAL:
            return True
        return category not in self.unsubscribed_categories

    def is_topic_subscribed(self, topic: NotificationTopic) -> bool:
        """Return whether the recipient receives a specific registered topic."""
        if topic.category is NotificationCategory.CRITICAL:
            return True
        return (
            topic.id not in self.unsubscribed_topics
            and topic.category not in self.unsubscribed_categories
        )
