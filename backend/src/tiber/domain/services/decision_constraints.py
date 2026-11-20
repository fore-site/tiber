"""Accept-time constraint computation (pure, no I/O).

Channel selection is explicit: a request either lists ``channels`` for a
registered recipient or supplies channel addresses, and this module validates
that set — every named channel needs a destination and must be renderable by
the template (with the supplied variables) or by the direct content. The worker
only fans out afterwards; it never picks a channel.

* Categories: the client's category if given, otherwise everything except
  CRITICAL. CRITICAL bypasses quiet hours, so a client must declare it; this
  also removes any conflict between an inferred category and a client `send_at`.
* ``in_app`` is address-backed like every other channel: it is deliverable
  only when an ``in_app`` address is configured or supplied.

An explicit selection is all-or-nothing: if any named channel cannot deliver,
the request is rejected with the reason, because the client asked for that
channel specifically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.exceptions import (
    ChannelNotAvailableError,
    InvalidEntityAttributeError,
)
from tiber.domain.services import validate_content
from tiber.domain.value_objects import NotificationContent
from tiber.domain.value_objects.intake import (
    ChannelMode,
    DecisionConstraints,
)

if TYPE_CHECKING:
    from tiber.domain.entities import Template

# Used when the client gives no category and the ML cannot (or does not) infer one.
DEFAULT_CATEGORY = NotificationCategory.INFORMATIONAL

_ML_INFERABLE_CATEGORIES = frozenset(NotificationCategory) - {
    NotificationCategory.CRITICAL
}


def compute_constraints(
    *,
    available_channels: frozenset[DeliveryChannel],
    adhoc: bool,
    requested_channels: Sequence[DeliveryChannel] | None,
    client_category: NotificationCategory | None,
    template: Template | None,
    template_variables: Mapping[str, Any] | None,
    content: NotificationContent | None,
) -> DecisionConstraints:
    """Validate the explicit channel set, or raise ``ChannelNotAvailableError``.

    ``available_channels`` is the recipient's registered address-backed
    channels, or for an address-based request, the channels the request
    supplied.
    """
    if adhoc and requested_channels:
        raise ValueError("`channels` cannot be combined with addresses")

    # 1. The explicit set. Every channel, including in-app, must have an address.
    deliverable = set(available_channels)

    mode: ChannelMode
    if adhoc:
        candidates, mode = deliverable, "addresses"
    elif requested_channels:
        candidates, mode = set(requested_channels), "client"
        missing = candidates - deliverable
        if missing:
            raise ChannelNotAvailableError(
                f"No registered destination for: {_names(missing)}"
            )
    else:
        # Reachable only by a caller that skipped the API contract: the domain
        # does not invent channels.
        raise ChannelNotAvailableError(
            "Choose channels explicitly: pass `channels` with `recipient`, or "
            "supply a channel address."
        )

    if DeliveryChannel.SMS in candidates:
        raise ChannelNotAvailableError("SMS delivery is coming soon.")

    # 2. Every named channel must be renderable. The client asked for these, so
    # none of them may silently drop out.
    provided = set(template_variables or {})
    problems: dict[DeliveryChannel, str] = {}
    for channel in candidates:
        reason = _render_problem(channel, template, provided, content)
        if reason is not None:
            problems[channel] = reason
    if problems:
        raise ChannelNotAvailableError(_describe(problems))

    # 3. Categories.
    if client_category is not None:
        allowed, default = frozenset({client_category}), client_category
    else:
        allowed, default = _ML_INFERABLE_CATEGORIES, DEFAULT_CATEGORY

    return DecisionConstraints(
        allowed_categories=allowed,
        default_category=default,
        channel_mode=mode,
    )


def _render_problem(
    channel: DeliveryChannel,
    template: Template | None,
    provided_variables: set[str],
    content: NotificationContent | None,
) -> str | None:
    """Why ``channel`` cannot deliver this notification, or ``None`` if it can."""
    if template is not None:
        if channel not in template.variants:
            return "the template has no variant for this channel"
        # Per channel, not the template-wide union: a send to one channel only
        # needs that variant's variables.
        missing = template.variables_for(channel) - provided_variables
        if missing:
            return f"missing template variables {sorted(missing)}"
        return None

    if content is None:
        return "no content provided"
    try:
        validate_content(channel, content)
    except (InvalidEntityAttributeError, ValueError) as exc:
        return str(exc)
    return None


def _names(channels: set[DeliveryChannel] | frozenset[DeliveryChannel]) -> list[str]:
    return sorted(ch.value for ch in channels)


def _describe(problems: Mapping[DeliveryChannel, str]) -> str:
    return "; ".join(
        f"{ch.value}: {why}"
        for ch, why in sorted(problems.items(), key=lambda p: p[0].value)
    )
