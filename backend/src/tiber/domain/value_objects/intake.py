"""Value objects for the accept/process split.

Vocabulary
----------
IntakePayload        what the client asked for, validated and resolved at accept time
DecisionConstraints  what the ML is *allowed* to choose from (computed at accept time)
MlSuggestion         raw, untrusted ML output
NotificationPlan     the trusted decision: client values, conformed ML values, or defaults,
                     each with its provenance
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.exceptions import InvalidEntityAttributeError
from tiber.domain.value_objects import NotificationContent

# How the channel set was chosen. ("default" = the ML was unavailable or its
# answer was unusable and the deterministic fallback was applied.)
ChannelSource = Literal["client", "ml", "addresses", "default"]

# Provenance of category and topic. Only "client" values are training labels.
DecisionSource = Literal["client", "ml", "default"]

# client    -> the client listed ``channels``
# addresses -> the client supplied addresses (the addresses are the set)
# ml        -> the ML chooses among ``feasible_channels``
ChannelMode = Literal["client", "addresses", "ml"]

# What the worker still needs the ML to decide.
Want = Literal["category", "topic", "channels", "send_time"]


# Lookup results


@dataclass(frozen=True)
class ResolvedTopic:
    """Snapshot of a topic taken at accept time."""

    id: UUID
    slug: str
    category: NotificationCategory


# Intake payload


@dataclass(frozen=True)
class IntakePayload:
    """The validated client request, with slugs resolved."""

    category: NotificationCategory | None = (
        None  # None -> the topic's, else the ML infers
    )
    topic: ResolvedTopic | None = (
        None  # the CLIENT's topic; None -> the ML may infer one
    )
    channels: tuple[DeliveryChannel, ...] | None = None  # registered recipients only
    adhoc_channels: frozenset[DeliveryChannel] | None = None  # address-based requests
    template_id: UUID | None = None
    template_slug: str | None = None
    template_variables: dict[str, Any] | None = None
    content: NotificationContent | None = None
    group_key: str | None = None
    send_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the invariants after initialization."""
        if self.channels is not None and self.adhoc_channels is not None:
            raise InvalidEntityAttributeError(
                "`channels` and address-based delivery are mutually exclusive"
            )
        if self.channels is not None and not self.channels:
            raise InvalidEntityAttributeError("`channels` must not be empty")
        if self.adhoc_channels is not None and not self.adhoc_channels:
            raise InvalidEntityAttributeError("`adhoc_channels` must not be empty")
        if self.template_id is None and self.content is None:
            raise InvalidEntityAttributeError(
                "Either a template or direct content is required"
            )
        if self.template_id is None and self.template_variables is not None:
            raise InvalidEntityAttributeError(
                "`template_variables` requires a template"
            )
        if (
            self.category is not None
            and self.topic is not None
            and self.category != self.topic.category
        ):
            raise InvalidEntityAttributeError(
                f"`category` {self.category.value!r} conflicts with topic "
                f"{self.topic.slug!r}, which belongs to category "
                f"{self.topic.category.value!r}. Omit `category` to use the topic's, "
                "or choose a topic in that category."
            )
        if self.send_at is not None:
            if self.send_at.tzinfo is None:
                raise InvalidEntityAttributeError("`send_at` must be timezone-aware")
            if self.declared_category is NotificationCategory.CRITICAL:
                raise InvalidEntityAttributeError(
                    "`send_at` must not be set for CRITICAL notifications; "
                    "they are sent immediately"
                )

    @property
    def declared_category(self) -> NotificationCategory | None:
        """The category the client has effectively declared.

        The explicit ``category``, else the category of the client's topic. ``None``
        when the client declared neither, which is the only case where the ML is
        asked for a category.
        """
        if self.category is not None:
            return self.category
        if self.topic is not None:
            return self.topic.category
        return None


# Constraints


@dataclass(frozen=True)
class DecisionConstraints:
    """The space the ML may choose from. Anything inside it is valid by construction."""

    allowed_categories: frozenset[NotificationCategory]
    default_category: NotificationCategory
    channel_mode: ChannelMode
    feasible_channels: frozenset[DeliveryChannel]
    max_channels: int

    def __post_init__(self) -> None:
        """Validate the invariants after initialization."""
        if not self.feasible_channels:
            raise InvalidEntityAttributeError("`feasible_channels` must not be empty")
        if self.max_channels < 1:
            raise InvalidEntityAttributeError("`max_channels` must be at least 1")
        if self.default_category not in self.allowed_categories:
            raise InvalidEntityAttributeError(
                "`default_category` must be one of `allowed_categories`"
            )


# ML output and the trusted plan


@dataclass(frozen=True)
class MlSuggestion:
    """Raw ML output. Untrusted: every field is checked against the constraints."""

    category: NotificationCategory | None = None
    topic_slug: str | None = None
    channels: tuple[DeliveryChannel, ...] = ()  # priority order
    send_at: Mapping[DeliveryChannel, datetime] = field(default_factory=dict)
    model_version: str | None = None


@dataclass(frozen=True)
class NotificationPlan:
    """The decision the worker acts on, stored on the intake before fan-out."""

    category: NotificationCategory
    category_source: DecisionSource
    topic: ResolvedTopic | None
    topic_source: DecisionSource | None  # None when there is no topic
    channels: tuple[DeliveryChannel, ...]
    channel_source: ChannelSource
    send_at: Mapping[DeliveryChannel, datetime] = field(default_factory=dict)
    model_version: str | None = None

    def __post_init__(self) -> None:
        """Validate the invariants after initialization."""
        if not self.channels:
            raise InvalidEntityAttributeError("A plan needs at least one channel")
        if len(set(self.channels)) != len(self.channels):
            raise InvalidEntityAttributeError("Plan channels must be unique")
        if not set(self.send_at) <= set(self.channels):
            raise InvalidEntityAttributeError(
                "`send_at` names a channel not in the plan"
            )
        if any(ts.tzinfo is None for ts in self.send_at.values()):
            raise InvalidEntityAttributeError("Plan send times must be timezone-aware")
