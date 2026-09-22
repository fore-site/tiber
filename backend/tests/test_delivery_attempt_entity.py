"""Entity pins for the DeliveryAttempt address snapshot.

``recipient_address`` freezes, at dispatch time, the address the provider
was given. ``Recipient.addresses`` is mutable, so without the snapshot the
question "what address did attempt #2 actually hit?" becomes
unreconstructable once the profile changes.

The invariant encodes what the field *means*: a succeeded attempt
contacted something, so its snapshot cannot be empty; a failed attempt may
have failed before any contact (no address on file for the channel), so
there ``None`` is legal and means "nothing was attempted" - never
"unknown address".
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tiber.domain.entities import DeliveryAttempt
from tiber.domain.enums import DeliveryAttemptStatus


def test_succeeded_attempt_requires_recipient_address():
    """A success contacted a real address: the snapshot cannot be missing."""
    with pytest.raises(ValueError, match="recipient_address"):
        DeliveryAttempt.create(
            notification_id=uuid4(),
            attempt_number=1,
            status=DeliveryAttemptStatus.SUCCEEDED,
            channel="email",
            provider="postmark",
            recipient_address=None,
        )


def test_failed_attempt_may_precede_any_contact():
    """None snapshot on a failure means 'failed before contact', and is legal."""
    attempt = DeliveryAttempt.create(
        notification_id=uuid4(),
        attempt_number=1,
        status=DeliveryAttemptStatus.FAILED,
        channel="sms",
        provider="twilio",
        recipient_address=None,
        error="no sms address for recipient",
    )

    assert attempt.recipient_address is None


def test_failed_attempt_still_snapshots_when_contact_was_made():
    """A failure after contact records the address the provider rejected."""
    attempt = DeliveryAttempt.create(
        notification_id=uuid4(),
        attempt_number=1,
        status=DeliveryAttemptStatus.FAILED,
        channel="email",
        provider="postmark",
        recipient_address="bounce@x.com",
        error="hard bounce",
    )

    assert attempt.recipient_address == "bounce@x.com"
