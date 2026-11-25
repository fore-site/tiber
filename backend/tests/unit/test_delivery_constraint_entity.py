"""Tests for the delivery constraint entity's invariants.

The project timezone is configuration, not a fact about a person, so it
defaults to UTC and may never be empty. It must also resolve: policy rules
call ``ZoneInfo(delivery_constraint.timezone)`` with no fallback, so the
fail-closed boundary for a bogus zone is here, at construction, rather than
an unresolvable zone quietly evaluating windows in the wrong timezone.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tiber.domain.entities import DeliveryConstraint
from tiber.domain.exceptions import InvalidEntityAttributeError


def test_unknown_timezone_is_rejected_at_construction():
    """Pin that a zone tzdata cannot resolve never reaches a policy rule."""
    with pytest.raises(
        InvalidEntityAttributeError, match="Unknown or missing timezone"
    ):
        DeliveryConstraint.create(project_id=uuid4(), timezone="Mars/Olympus_Mons")


def test_malformed_timezone_is_rejected_at_construction():
    """Pin that a non-IANA key is rejected too, not just a resolvable-looking one."""
    with pytest.raises(InvalidEntityAttributeError, match="Invalid timezone format"):
        DeliveryConstraint.create(project_id=uuid4(), timezone="../not-a-zone")


def test_reconstitute_validates_the_timezone_it_loads():
    """Pin that a stored zone tzdata has since dropped fails on load.

    This is the fail-closed behavior for a tzdata update that removes a zone:
    the request that loads the constraint fails loudly instead of evaluating
    quiet hours in an unrelated zone.
    """
    with pytest.raises(
        InvalidEntityAttributeError, match="Unknown or missing timezone"
    ):
        DeliveryConstraint.reconstitute(
            id=uuid4(),
            project_id=uuid4(),
            blackout_periods=[],
            quiet_hours=[],
            timezone="Mars/Olympus_Mons",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
