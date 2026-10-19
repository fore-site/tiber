"""Accept-time constraint computation (pure, no I/O).

The API cannot validate ML output synchronously, because the ML runs later in a
worker. Instead it validates the *space* the ML may choose from, so anything the
ML returns is valid by construction:

* Channels: only channels that have an address AND can actually be rendered
  (a template body exists with all its variables, or the direct content passes
  that channel's validation).
* Categories: the client's category if given, otherwise everything except
  CRITICAL. CRITICAL bypasses quiet hours, so a client must declare it; this
  also removes any conflict between an inferred category and a client `send_at`.
* Channel count: a template can fan out to several channels; direct content
  yields exactly one ML-chosen channel.

Explicit selections (``channels`` or supplied addresses) are all-or-nothing: if
any named channel cannot deliver, the request is rejected with the reason,
because the client asked for that channel specifically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

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
    TemplateInfo,
)

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
    opted_out: frozenset[DeliveryChannel],
    client_category: NotificationCategory | None,
    template: TemplateInfo | None,
    template_variables: Mapping[str, Any] | None,
    content: NotificationContent | None,
) -> DecisionConstraints:
    """Compute the decision space, or raise ``ChannelNotAvailableError`` (422).

    ``available_channels`` is the recipient's registered channels, or for an
    address-based request, the channels the request supplied.
    """
    if adhoc and requested_channels:
        raise ValueError("`channels` cannot be combined with addresses")

    # 1. Candidate channels and who decides among them.
    mode: ChannelMode
    if adhoc:
        candidates, mode = set(available_channels), "addresses"
    elif requested_channels:
        candidates, mode = set(requested_channels), "client"
        missing = candidates - available_channels
        if missing:
            raise ChannelNotAvailableError(
                f"No registered address for: {_names(missing)}"
            )
    else:
        candidates, mode = set(available_channels), "ml"

    # 2. Which candidates can actually be rendered and delivered?
    provided = set(template_variables or {})
    problems: dict[DeliveryChannel, str] = {}
    for channel in candidates:
        reason = _render_problem(channel, template, provided, content)
        if reason is not None:
            problems[channel] = reason

    # 3. Channels.
    if mode != "ml":
        # The client named these channels; none may silently drop out.
        if problems:
            raise ChannelNotAvailableError(_describe(problems))
        feasible = frozenset(candidates)
        max_channels = len(feasible)
    else:
        feasible = frozenset(candidates - set(problems))
        if not feasible:
            raise ChannelNotAvailableError(
                "No channel can deliver this notification: " + _describe(problems)
            )
        # Don't let the ML pick a channel the recipient opted out of, which
        # would only produce a suppressed record. If every deliverable channel
        # is opted out, keep them all so the suppression is recorded visibly.
        reachable = feasible - opted_out
        if reachable:
            feasible = reachable
        max_channels = len(feasible) if template is not None else 1

    # 4. Categories.
    if client_category is not None:
        allowed, default = frozenset({client_category}), client_category
    else:
        allowed, default = _ML_INFERABLE_CATEGORIES, DEFAULT_CATEGORY

    return DecisionConstraints(
        allowed_categories=allowed,
        default_category=default,
        channel_mode=mode,
        feasible_channels=feasible,
        max_channels=max_channels,
    )


def _render_problem(
    channel: DeliveryChannel,
    template: TemplateInfo | None,
    provided_variables: set[str],
    content: NotificationContent | None,
) -> str | None:
    """Why ``channel`` cannot deliver this notification, or ``None`` if it can."""
    if template is not None:
        if channel not in template.channels:
            return "no template exists for this channel"
        missing = (
            template.required_variables.get(channel, frozenset()) - provided_variables
        )
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
