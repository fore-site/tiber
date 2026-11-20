"""Plan assembly: the client owns the channel set, the ML never adds one."""

from datetime import UTC, datetime

import pytest

from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.services.plan_assembly import assemble_plan, wanted_decisions
from tiber.domain.value_objects import NotificationContent
from tiber.domain.value_objects.intake import (
    ChannelMode,
    DecisionConstraints,
    IntakePayload,
    MlSuggestion,
)

_NOW = datetime(2030, 1, 1, tzinfo=UTC)


def _constraints(mode: ChannelMode) -> DecisionConstraints:
    """Constraints as the accept path builds them."""
    return DecisionConstraints(
        allowed_categories=frozenset({NotificationCategory.INFORMATIONAL}),
        default_category=NotificationCategory.INFORMATIONAL,
        channel_mode=mode,
    )


def _payload() -> IntakePayload:
    return IntakePayload(content=NotificationContent(title="Hi", plain_text_body="Hi"))


@pytest.mark.parametrize("mode", ["client", "addresses"])
def test_channels_are_never_a_decision(mode: ChannelMode) -> None:
    """The client names the channels, so the ML is never asked for them."""
    assert "channels" not in wanted_decisions(_payload(), _constraints(mode))


def test_ml_cannot_change_the_channel_set() -> None:
    """A suggestion still decides open fields, but never the channels."""
    payload = IntakePayload(
        channels=(DeliveryChannel.EMAIL,),
        content=NotificationContent(title="Hi", plain_text_body="Hi"),
    )
    plan = assemble_plan(
        payload=payload,
        constraints=_constraints("client"),
        ml=MlSuggestion(category=NotificationCategory.INFORMATIONAL),
        ml_topic=None,
        now=_NOW,
    )

    assert plan.channels == (DeliveryChannel.EMAIL,)
    assert plan.channel_source == "client"
    # The engine did run: it just cannot reach the channel decision.
    assert plan.category_source == "ml"
