from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING
from uuid import UUID

from ..enums import DeliveryChannel, NotificationCategory

if TYPE_CHECKING:
    from collections.abc import Collection

    from ..entities import NotificationTopic
    from .blackout_period import BlackoutPeriod
    from .quiet_hours import QuietHours


class Unset:
    """Sentinel distinguishing an omitted preference from an explicit clear.

    Public because it appears in application and API signatures: ``None``
    already means "clear this preference", so "not supplied" needs a value of
    its own that no caller can accidentally pass as a real restriction.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """Render as the sentinel's name, so logs read ``UNSET``."""
        return "UNSET"


UNSET = Unset()


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

    def merged_with(
        self,
        *,
        opted_out_channels: Collection[DeliveryChannel] | None = None,
        unsubscribed_categories: Collection[NotificationCategory] | None = None,
        unsubscribed_topics: Collection[UUID] | None = None,
        blackout_period: BlackoutPeriod | None | Unset = UNSET,
        quiet_hours: QuietHours | None | Unset = UNSET,
    ) -> RecipientPreferences:
        """Return a copy with only the supplied preferences replaced.

        For the consent sets, ``None`` means "not supplied" and leaves that set
        untouched; an empty collection explicitly clears it. Time preferences
        use ``UNSET`` for "not supplied" because ``None`` is a meaningful
        value: it clears the stored restriction. ``replace`` re-runs
        ``__post_init__``, so the merged result is subject to the same
        invariants.
        """
        return replace(
            self,
            opted_out_channels=(
                self.opted_out_channels
                if opted_out_channels is None
                else frozenset(opted_out_channels)
            ),
            unsubscribed_categories=(
                self.unsubscribed_categories
                if unsubscribed_categories is None
                else frozenset(unsubscribed_categories)
            ),
            unsubscribed_topics=(
                self.unsubscribed_topics
                if unsubscribed_topics is None
                else frozenset(unsubscribed_topics)
            ),
            blackout_period=(
                self.blackout_period
                if isinstance(blackout_period, Unset)
                else blackout_period
            ),
            quiet_hours=(
                self.quiet_hours if isinstance(quiet_hours, Unset) else quiet_hours
            ),
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
