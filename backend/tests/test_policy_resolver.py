"""Tests for the delivery policy engine and worker-time guard.

Pure-Python tests - no database or broker required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from tiber.application.services import DeliveryPolicyGuard
from tiber.domain.entities import Notification, Recipient
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.policies import PolicyDecision, PolicyResolver
from tiber.domain.value_objects import NotificationContent, RecipientPreferences


def make_notification(channel: DeliveryChannel = DeliveryChannel.EMAIL) -> Notification:
    """Build a pending notification for the given channel."""
    return Notification.create(
        project_id=uuid4(),
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=channel,
        category=NotificationCategory.PROMOTIONAL,
        content=NotificationContent(
            title="Hi" if channel == DeliveryChannel.EMAIL else None,
            body="Hello",
        ),
    )


def make_recipient(
    notification: Notification,
    addresses: dict[str, str],
    opted_out: list[DeliveryChannel] | None = None,
) -> Recipient:
    """Build a recipient belonging to the notification."""
    # String keys are the wire format; the helper is the boundary that
    # converts to domain vocabulary (same as repo rehydration does).
    return Recipient.reconstitute(
        id=uuid4(),
        project_id=notification.project_id,
        addresses={
            DeliveryChannel(channel): value for channel, value in addresses.items()
        },
        preferences=RecipientPreferences(opted_out_channels=opted_out or frozenset()),
        external_id=None,
        timezone=None,
        language=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        archived_at=None,
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


async def test_guard_does_not_recheck_address():
    """The dispatch guard omits the address rule (doc 04's contract).

    An address cannot usefully drift between intake and dispatch, and
    re-classifying a missing address as policy_rejected would mislabel a
    lookup/attempt failure. The processor's own missing-address check
    guards that path with a failed attempt instead.
    """
    notification = make_notification(DeliveryChannel.EMAIL)
    recipient = make_recipient(notification, {"push": "token"})  # no email

    decision = await DeliveryPolicyGuard().check(notification, recipient)

    assert decision.allowed


async def test_guard_reports_drift_sensitive_rejection_with_reason():
    """The guard rejects on the drift-sensitive rules with a usable reason."""
    notification = make_notification(DeliveryChannel.EMAIL)
    recipient = make_recipient(
        notification,
        {"email": "a@b.io"},
        opted_out=[DeliveryChannel.EMAIL],  # consent changed since intake
    )

    decision = await DeliveryPolicyGuard().check(notification, recipient)

    assert not decision.allowed
    assert decision.reason is not None and "opted out" in decision.reason


async def test_guard_with_custom_resolver_rules():
    """A guard wired to a custom rule set uses only those rules."""
    from tiber.domain.policies.rules import PolicyRule, RecipientPreferenceRule

    class AlwaysBlock(PolicyRule):
        name = "always_block"

        async def evaluate(self, ctx) -> PolicyDecision:
            return PolicyDecision.reject("nope", rule=self.name)

    notification = make_notification(DeliveryChannel.EMAIL)
    recipient = make_recipient(notification, {"email": "a@b.io"})

    guard = DeliveryPolicyGuard(
        PolicyResolver(rules=[RecipientPreferenceRule(), AlwaysBlock()])
    )
    decision = await guard.check(notification, recipient)

    assert not decision.allowed
    assert decision.rule == "always_block"
