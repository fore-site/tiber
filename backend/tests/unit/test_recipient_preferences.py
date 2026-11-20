"""Recipient consent state: schema validation, persistence, response shape."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from tiber.api.schemas.recipient import (
    RecipientCreateRequest,
    RecipientPreferencesRequest,
    RecipientResponse,
)
from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.value_objects import RecipientPreferences
from tiber.infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)


def make_recipient(
    preferences: RecipientPreferences | None = None,
) -> Recipient:
    """Build a recipient that can legitimately opt out of SMS."""
    return Recipient.create(
        project_id=uuid4(),
        external_id="user-1",
        addresses={
            DeliveryChannel.EMAIL: "jane@example.com",
            DeliveryChannel.SMS: "+15551234567",
        },
        preferences=preferences,
    )


# --- In-app addressing ---


def test_registration_accepts_an_in_app_address():
    """In-app addresses are configured like every other channel."""
    payload = RecipientCreateRequest(
        external_id="user-1",
        addresses={"in_app": "user-1"},
    )

    assert payload.addresses == {DeliveryChannel.IN_APP: "user-1"}


def test_in_app_can_be_opted_out_when_an_address_exists():
    """Consent and addressing agree once in-app has a stored destination."""
    recipient = Recipient.create(
        project_id=uuid4(),
        external_id="user-1",
        addresses={DeliveryChannel.IN_APP: "user-1"},
        preferences=RecipientPreferences(opted_out_channels=[DeliveryChannel.IN_APP]),
    )

    assert DeliveryChannel.IN_APP in recipient.preferences.opted_out_channels


def test_response_exposes_the_in_app_address():
    """The response is the readable copy of the stored address book."""
    recipient = Recipient.create(
        project_id=uuid4(),
        external_id="user-1",
        addresses={DeliveryChannel.IN_APP: "user-1"},
    )

    payload = RecipientResponse.from_entity(recipient)

    assert payload.addresses == {"in_app": "user-1"}


# --- Persistence ---


def test_preferences_survive_a_persistence_round_trip():
    """The stored object rebuilds exactly the consent state it serialized."""
    topic = uuid4()
    preferences = RecipientPreferences(
        opted_out_channels=[DeliveryChannel.SMS],
        unsubscribed_categories=[NotificationCategory.PROMOTIONAL],
        unsubscribed_topics=[topic],
    )

    model = SQLAlchemyRecipientRepository._to_model(make_recipient(preferences))
    restored = SQLAlchemyRecipientRepository._to_entity(model)

    assert restored.preferences == preferences


def test_absent_preferences_read_as_fully_subscribed():
    """An empty stored object means no consent has been withdrawn."""
    model = SQLAlchemyRecipientRepository._to_model(make_recipient())

    restored = SQLAlchemyRecipientRepository._to_entity(model)

    assert restored.preferences == RecipientPreferences()


def test_preferences_serialize_to_stable_sorted_values():
    """Channel and category keys are stored as their enum values."""
    model = SQLAlchemyRecipientRepository._to_model(
        make_recipient(
            RecipientPreferences(
                opted_out_channels=[DeliveryChannel.SMS, DeliveryChannel.EMAIL]
            )
        )
    )

    assert model.preferences["opted_out_channels"] == ["email", "sms"]


# --- Request schema ---


def test_critical_category_cannot_be_unsubscribed():
    """CRITICAL is always deliverable; the wire contract says so up front."""
    with pytest.raises(ValidationError, match="CRITICAL"):
        RecipientPreferencesRequest(unsubscribed_categories=["critical"])


def test_duplicate_entries_are_rejected():
    """Duplicates are a client mistake, not something to silently collapse."""
    with pytest.raises(ValidationError, match="duplicates"):
        RecipientPreferencesRequest(opted_out_channels=["email", "email"])


def test_omitted_request_fields_mean_no_change():
    """Absence is distinguishable from an explicit empty list."""
    payload = RecipientPreferencesRequest()

    assert payload.opted_out_channels is None
    assert payload.unsubscribed_categories is None
    assert payload.unsubscribed_topics is None


# --- Merge semantics ---


def test_merge_leaves_omitted_sets_untouched():
    """Updating one set does not disturb the other two."""
    topic = uuid4()
    current = RecipientPreferences(
        opted_out_channels=[DeliveryChannel.SMS],
        unsubscribed_categories=[NotificationCategory.PROMOTIONAL],
        unsubscribed_topics=[topic],
    )

    merged = current.merged_with(opted_out_channels=[DeliveryChannel.EMAIL])

    assert merged.opted_out_channels == frozenset({DeliveryChannel.EMAIL})
    assert merged.unsubscribed_categories == current.unsubscribed_categories
    assert merged.unsubscribed_topics == current.unsubscribed_topics


def test_empty_list_clears_a_set():
    """An explicit empty list is how a client re-subscribes."""
    current = RecipientPreferences(opted_out_channels=[DeliveryChannel.SMS])

    merged = current.merged_with(opted_out_channels=[])

    assert merged.opted_out_channels == frozenset()


def test_merge_still_rejects_critical_unsubscribe():
    """The wire validator is not the only guard on CRITICAL."""
    with pytest.raises(ValueError, match="CRITICAL"):
        RecipientPreferences().merged_with(unsubscribed_categories=["critical"])


# --- Response schema ---


def test_response_exposes_the_stored_consent_state():
    """Opt-outs and unsubscribes are readable on the recipient."""
    topic = uuid4()
    payload = RecipientResponse.from_entity(
        make_recipient(
            RecipientPreferences(
                opted_out_channels=[DeliveryChannel.SMS],
                unsubscribed_categories=[NotificationCategory.PROMOTIONAL],
                unsubscribed_topics=[topic],
            )
        )
    )

    assert payload.opted_out_channels == [DeliveryChannel.SMS]
    assert payload.unsubscribed_categories == [NotificationCategory.PROMOTIONAL]
    assert payload.unsubscribed_topics == [topic]
