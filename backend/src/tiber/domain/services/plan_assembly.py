"""Plan assembly (pure, no I/O).

For every decision the client left open, take the ML's answer only if it falls
inside the accept-time constraints; otherwise apply a deterministic default.
This is what makes the ML advisory: an outage, a timeout or a nonsense answer
degrades quality, never correctness, and never fails the intake.

Precedence per decision: client value > conformed ML value > default. Channels
are never a decision: they come from the client, either enumerated or implied by
the addresses it supplied.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.exceptions import InvalidEntityAttributeError
from tiber.domain.value_objects.intake import (
    ChannelSource,
    DecisionConstraints,
    IntakePayload,
    MlSuggestion,
    NotificationPlan,
    ResolvedTopic,
    Want,
)


def wanted_decisions(
    payload: IntakePayload, constraints: DecisionConstraints
) -> frozenset[Want]:
    """Return the decisions the ML still has to make.

    Channels are never among them: the client names them, or names the addresses
    that imply them. An empty result means skip the ML call. A client-declared
    CRITICAL notification never waits on the ML for category, topic or send time
    (it is sent immediately).
    """
    want: set[Want] = set()
    if payload.category is None:
        want.add("category")
    if payload.category is not NotificationCategory.CRITICAL:
        if payload.topic is None:
            want.add("topic")
        if payload.send_at is None:
            want.add("send_time")
    return frozenset(want)


def assemble_plan(
    *,
    payload: IntakePayload,
    constraints: DecisionConstraints,
    ml: MlSuggestion | None,
    ml_topic: ResolvedTopic | None,
    now: datetime,
) -> NotificationPlan:
    """Build the plan.

    ``ml_topic`` is the ML's topic suggestion after the caller verified that the
    slug exists in the project (``None`` if it does not, or if none was given).
    """
    category_source: Literal["client", "ml", "default"]
    topic_source: Literal["client", "ml", "default"] | None

    # category
    if payload.category is not None:
        category, category_source = payload.category, "client"
    elif ml is not None and (
        ml.category is not None and ml.category in constraints.allowed_categories
    ):
        category, category_source = ml.category, "ml"
    else:
        category, category_source = constraints.default_category, "default"

    # topic
    if payload.topic is not None:
        topic, topic_source = payload.topic, "client"
    elif ml_topic is not None:
        topic, topic_source = ml_topic, "ml"
    else:
        topic, topic_source = None, None

    # always the client's choice, never the ML's
    channels: tuple[DeliveryChannel, ...]
    channel_source: ChannelSource
    if constraints.channel_mode == "client":
        if payload.channels is None:
            raise InvalidEntityAttributeError("client channel mode requires `channels`")
        channels, channel_source = tuple(dict.fromkeys(payload.channels)), "client"
    elif constraints.channel_mode == "addresses":
        if payload.adhoc_channels is None:
            raise InvalidEntityAttributeError(
                "addresses channel mode requires `adhoc_channels`"
            )
        channels = tuple(sorted(payload.adhoc_channels, key=lambda c: c.value))
        channel_source = "addresses"
    else:
        raise InvalidEntityAttributeError(
            f"unsupported channel mode {constraints.channel_mode!r}: channel "
            "selection is explicit"
        )

    # send times (ML-predicted only; client send_at and CRITICAL need none)
    send_at: dict[DeliveryChannel, datetime] = {}
    if (
        ml is not None
        and payload.send_at is None
        and category is not NotificationCategory.CRITICAL
    ):
        send_at = {
            ch: ts
            for ch, ts in ml.send_at.items()
            if ch in channels and ts.tzinfo is not None and ts > now
        }

    return NotificationPlan(
        category=category,
        category_source=category_source,
        topic=topic,
        topic_source=topic_source,
        channels=channels,
        channel_source=channel_source,
        send_at=send_at,
        model_version=ml.model_version if ml is not None else None,
    )
