"""Tests for the delivery policy engine and worker-time guard.

Pure-Python tests - no database or broker required.
"""

from __future__ import annotations

from uuid import uuid4

from tiber.application.services import (
    DeliveryPolicyGuard,
    PolicyResolver,
)
from tiber.domain.entities import Notification, Recipient
from tiber.domain.enums import DeliveryChannel
from tiber.domain.policies import PolicyDecision
from tiber.domain.value_objects import NotificationContent


def make_notification(channel: DeliveryChannel = DeliveryChannel.EMAIL) -> Notification:
    """Build a pending notification for the given channel."""
    return Notification(
        id=uuid4(),
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=channel,
        content=NotificationContent(
            subject="Hi" if channel == DeliveryChannel.EMAIL else None,
            body="Hello",
        ),
    )


def make_recipient(
    notification: Notification,
    addresses: dict,
    opted_out: list[DeliveryChannel] | None = None,
) -> Recipient:
    """Build a recipient belonging to the notification."""
    return Recipient(
        id=notification.recipient_id,
        project_id=notification.project_id,
        addresses=addresses,
        opted_out_channels=opted_out or [],
    )


# --- PolicyResolver (default rule chain: opt-out then address) ---


async def test_resolver_allows_when_address_present_and_channel_enabled():
    """A well-addressed, opted-in recipient is allowed through."""
    notification = make_notification(DeliveryChannel.EMAIL)
    recipient = make_recipient(notification, {"email": "a@b.io"})

    decision = await PolicyResolver().evaluate(notification, recipient)

    assert decision.allowed


async def test_resolver_rejects_when_channel_opted_out():
    """An explicit opt-out rejects with a preference reason."""
    notification = make_notification(DeliveryChannel.PUSH)
    recipient = make_recipient(
        notification, {"push": "token"}, opted_out=[DeliveryChannel.PUSH]
    )

    decision = await PolicyResolver().evaluate(notification, recipient)

    assert not decision.allowed
    assert decision.reason is not None and "opted out" in decision.reason


async def test_resolver_rejects_when_recipient_missing_channel_address():
    """A missing channel address rejects with an address reason."""
    notification = make_notification(DeliveryChannel.EMAIL)
    recipient = make_recipient(notification, {"push": "token"})  # no email

    decision = await PolicyResolver().evaluate(notification, recipient)

    assert not decision.allowed
    assert decision.reason is not None and "no email address" in decision.reason


async def test_resolver_short_circuits_on_first_rejection():
    """Rules run in order; the first rejection wins."""
    from tiber.domain.policies.rules import PolicyRule

    class AlwaysBlock(PolicyRule):
        def __init__(self, name: str) -> None:
            self.name = name

        async def evaluate(self, ctx) -> PolicyDecision:
            return PolicyDecision.reject("nope", rule=self.name)

    notification = make_notification(DeliveryChannel.EMAIL)
    recipient = make_recipient(notification, {"email": "a@b.io"})

    resolver = PolicyResolver(rules=[AlwaysBlock("first"), AlwaysBlock("second")])

    decision = await resolver.evaluate(notification, recipient)

    assert not decision.allowed
    assert decision.rule == "first"


# --- DeliveryPolicyGuard (worker-time re-check) ---


async def test_guard_reports_allowed_for_valid_recipient():
    """The guard surfaces an allow decision unchanged."""
    notification = make_notification(DeliveryChannel.EMAIL)
    recipient = make_recipient(notification, {"email": "a@b.io"})

    decision = await DeliveryPolicyGuard().check(notification, recipient)

    assert decision.allowed


async def test_guard_reports_rejection_with_reason():
    """The guard surfaces a rejection with a usable policy_violation_reason."""
    notification = make_notification(DeliveryChannel.EMAIL)
    # No email address -> the address rule rejects with a usable reason.
    recipient = make_recipient(notification, {"push": "token"})

    decision = await DeliveryPolicyGuard().check(notification, recipient)

    assert not decision.allowed
    assert decision.reason


async def test_guard_with_custom_resolver_rules():
    """A guard wired to a custom rule set uses only those rules."""
    from tiber.domain.policies.rules import ChannelPreferenceRule, PolicyRule

    class AlwaysBlock(PolicyRule):
        name = "always_block"

        async def evaluate(self, ctx) -> PolicyDecision:
            return PolicyDecision.reject("nope", rule=self.name)

    notification = make_notification(DeliveryChannel.EMAIL)
    recipient = make_recipient(notification, {"email": "a@b.io"})

    guard = DeliveryPolicyGuard(
        PolicyResolver(rules=[ChannelPreferenceRule(), AlwaysBlock()])
    )
    decision = await guard.check(notification, recipient)

    assert not decision.allowed
    assert decision.rule == "always_block"
