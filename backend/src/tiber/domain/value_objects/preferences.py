"""Recipient consent preferences as an immutable value object.

Storage semantics are opt-out (an absent preference set means fully
subscribed); consent itself is collected opt-in by the client application,
which is responsible for seeding these sets from the consent it gathered
at its own sign-up surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from ..enums import DeliveryChannel, NotificationCategory

if TYPE_CHECKING:
    # Type-only: importing the entity at runtime would create a circular
    # import (entities.topic imports this package for TopicTitle).
    from ..entities import NotificationTopic


@dataclass(frozen=True)
class RecipientPreferences:
    """Value object holding a recipient's consent state.

    Three consent collections, each normalized to a frozenset:

    - ``opted_out_channels``: channels the recipient refuses outright.
    - ``unsubscribed_categories``: notification categories the recipient
      has unsubscribed from, across all topics and channels.
    - ``unsubscribed_topics``: ids of registered NotificationTopics the
      recipient has unsubscribed from. Ids, never slugs: slugs are
      client-facing and renameable; identity is stable.

    INVARIANT: ``NotificationCategory.CRITICAL`` is unstorable. The
    essential category is always deliverable, so unsubscribing from it is
    unrepresentable rather than merely ignored - enforced at construction,
    the only place consent state is created.

    Topic ids are opaque to this object: it cannot know which category a
    topic maps to. A CRITICAL-mapped topic id inside ``unsubscribed_topics``
    is therefore harmless - ``is_topic_subscribed`` short-circuits on the
    topic's category before consulting any stored state.
    """

    opted_out_channels: frozenset[DeliveryChannel] = field(default_factory=frozenset)
    unsubscribed_categories: frozenset[NotificationCategory] = field(
        default_factory=frozenset
    )
    unsubscribed_topics: frozenset[UUID] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        """Normalize inputs and enforce the CRITICAL-unstorable invariant.

        Accepts raw strings and enum members (rehydration and API payloads
        arrive untyped); an unknown channel or category value raises the
        enum's ValueError rather than being silently dropped.
        """
        channels = frozenset(
            DeliveryChannel(channel.lower()) for channel in self.opted_out_channels
        )

        categories = frozenset(
            NotificationCategory(category.lower())
            for category in self.unsubscribed_categories
        )

        topics = frozenset(self.unsubscribed_topics)

        if NotificationCategory.CRITICAL in categories:
            raise ValueError(
                "CRITICAL notifications are always deliverable and cannot "
                "be unsubscribed from"
            )

        object.__setattr__(self, "opted_out_channels", channels)
        object.__setattr__(self, "unsubscribed_categories", categories)
        object.__setattr__(self, "unsubscribed_topics", topics)

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
        """Return whether the recipient receives a specific registered topic.

        The CRITICAL check must precede every stored-state consultation -
        including the topic-id set - so a CRITICAL-mapped topic stays
        deliverable no matter what a client seeded. This is why the bypass
        is written out here instead of delegated to ``is_subscribed``:
        delegation would let a seeded topic id silence a CRITICAL topic.
        """
        if topic.category is NotificationCategory.CRITICAL:
            return True
        return (
            topic.id not in self.unsubscribed_topics
            and topic.category not in self.unsubscribed_categories
        )
