"""Tests for Recipient profile, addresses, and claim lifecycle.

Pins:

- ``timezone``/``language`` are facts about a person: ``None`` means
  unknown, never a fabricated default (contrasts with
  DeliveryConstraint.timezone's UTC default — facts vs configuration).
- Facts validate on every construction path: create(), reconstitute(),
  direct instantiation all funnel through __post_init__, so an invalid
  fact is unrepresentable anywhere.
- set_profile_facts() is a full restatement, not a patch: passing None
  withdraws a fact. The copy carries a fresh updated_at.
- update_addresses() and update_preferences() replace their state group;
  update_addresses() enforces the non-empty invariant explicitly.
- claim_addresses() attaches a human identity: merges addresses
  (incoming wins), rejects empty/duplicate claims, stamps updated_at.
- Facts survive persistence round-trips (model column <-> entity field).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel
from tiber.domain.value_objects import RecipientPreferences


def make_recipient(**overrides) -> Recipient:
    """Build a valid email recipient, with overrides."""
    kwargs = dict(
        project_id=uuid4(),
        addresses={DeliveryChannel.EMAIL: "jane@example.com"},
        preferences=RecipientPreferences(),
    )
    kwargs.update(overrides)
    return Recipient.create(**kwargs)


# --- Facts default to unknown, never fabricated ---


def test_profile_facts_default_to_none():
    """A recipient without stated facts has unknown ones, not UTC defaults."""
    recipient = make_recipient()

    assert recipient.timezone is None
    assert recipient.language is None


# --- create() accepts and validates facts ---


def test_create_with_valid_facts():
    """Valid IANA zone and BCP-47 tag are stored as given."""
    recipient = make_recipient(timezone="Europe/Lisbon", language="pt-BR")

    assert recipient.timezone == "Europe/Lisbon"
    assert recipient.language == "pt-BR"


def test_create_rejects_unknown_timezone():
    """A non-IANA zone raises the same error shape as DeliveryConstraint."""
    with pytest.raises(ValueError, match="Invalid timezone"):
        make_recipient(timezone="Mars/Olympus_Mons")


def test_create_rejects_malformed_language():
    """Free text is not a language tag."""
    with pytest.raises(ValueError, match="language"):
        make_recipient(language="not a language!")


# --- reconstitute() validates too: bad stored facts cannot rehydrate ---


def test_reconstitute_validates_timezone():
    """Bad stored facts cannot rehydrate — rehydration validates, not trusts."""
    with pytest.raises(ValueError, match="Invalid timezone"):
        Recipient.reconstitute(
            id=uuid4(),
            project_id=uuid4(),
            addresses={DeliveryChannel.EMAIL: "jane@example.com"},
            preferences=RecipientPreferences(),
            external_id=None,
            timezone="Not/AZone",
            language="en",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            archived_at=None,
        )


# --- set_profile_facts(): full restatement semantics ---


def test_set_profile_facts_states_current_truth():
    """Setting facts bumps updated_at; the frozen original is untouched."""
    recipient = make_recipient()
    before = recipient.updated_at

    updated = recipient.set_profile_facts(timezone="Europe/Lisbon", language="pt")

    assert updated.timezone == "Europe/Lisbon"
    assert updated.language == "pt"
    assert updated.updated_at > before
    # Frozen entity: the original is untouched.
    assert recipient.timezone is None


def test_set_profile_facts_withdraws_a_fact():
    """None is a restatement to unknown, not a no-op patch."""
    recipient = make_recipient(timezone="Europe/Lisbon")

    updated = recipient.set_profile_facts(timezone=None, language="en")

    assert updated.timezone is None
    assert updated.language == "en"


def test_set_profile_facts_rejects_invalid_fact():
    """Validation runs on the mutation path too; failure leaves no trace."""
    recipient = make_recipient(timezone="Europe/Lisbon")

    with pytest.raises(ValueError, match="Invalid timezone"):
        recipient.set_profile_facts(timezone="Bogus/Zone", language="en")

    # The original survives untouched — frozen entity, invalid copy rejected.
    assert recipient.timezone == "Europe/Lisbon"


# --- update_addresses(): replaces the whole address book ---


def test_update_addresses_replaces_and_normalizes_keys():
    """The incoming mapping is the new state; raw string keys are coerced."""
    recipient = make_recipient()

    updated = recipient.update_addresses(
        {"sms": "+15551234567"}  # raw string key, not the enum member
    )

    assert set(updated.addresses) == {DeliveryChannel.SMS}
    assert DeliveryChannel.EMAIL not in updated.addresses


def test_update_addresses_rejects_empty():
    """The non-empty invariant is enforced on the mutation path too."""
    with pytest.raises(ValueError, match="must not be empty"):
        make_recipient().update_addresses({})


def test_update_addresses_respects_opt_out_invariant():
    """A opted-out channel cannot lose its address in the replacement."""
    recipient = make_recipient(
        preferences=RecipientPreferences(opted_out_channels=["sms"]),
        addresses={
            DeliveryChannel.EMAIL: "jane@example.com",
            DeliveryChannel.SMS: "+15551234567",
        },
    )

    with pytest.raises(ValueError, match="opted-out"):
        recipient.update_addresses({DeliveryChannel.EMAIL: "jane@example.com"})


# --- update_preferences(): consent replacement ---


def test_update_preferences_replaces_consent():
    """New consent state replaces the old wholesale."""
    recipient = make_recipient()

    updated = recipient.update_preferences(
        RecipientPreferences(unsubscribed_categories=["promotional"])
    )

    assert updated.preferences.unsubscribed_categories == frozenset({"promotional"})


# --- claim_addresses(): the doc 08 lifecycle event ---


def test_claim_attaches_identity_and_merges_addresses():
    """Ownerless + claim = registered; incoming addresses win on collision."""
    ownerless = make_recipient()  # no external_id

    claimed = ownerless.claim("user_12345", {DeliveryChannel.EMAIL: "new@example.com"})

    assert claimed.external_id == "user_12345"
    assert claimed.addresses[DeliveryChannel.EMAIL] == "new@example.com"


def test_claim_merges_without_dropping_existing_channels():
    """A claim adding a second channel keeps the first."""
    ownerless = make_recipient()

    claimed = ownerless.claim("user_12345", {DeliveryChannel.SMS: "+15551234567"})

    assert set(claimed.addresses) == {DeliveryChannel.EMAIL, DeliveryChannel.SMS}


def test_claim_rejects_empty_external_id():
    """An empty identity is not a claim."""
    with pytest.raises(ValueError, match="external_id"):
        make_recipient().claim("   ", {})


def test_claim_rejects_double_claim():
    """A claimed recipient cannot be re-claimed (doc 08: explicit act)."""
    claimed = make_recipient(external_id="user_12345")

    with pytest.raises(ValueError, match="already claimed"):
        claimed.claim("user_67890", {DeliveryChannel.SMS: "+15551234567"})


def test_claim_stamps_updated_at_and_leaves_original_frozen():
    """Mutation semantics: fresh stamp, original untouched."""
    ownerless = make_recipient()
    before = ownerless.updated_at

    claimed = ownerless.claim("user_12345", {DeliveryChannel.SMS: "+15551234567"})

    assert claimed.updated_at > before
    assert ownerless.external_id is None


# --- Facts survive the persistence round-trip ---


def test_facts_round_trip_through_model_mapping():
    """_to_model carries the facts into columns; _to_entity rehydrates them.

    Uses the repository's static mappers directly — the same code path a
    session save/load exercises — so a column omission shows up here as a
    None rehydrated where a fact was set.
    """
    from tiber.infrastructure.repositories.sqlalchemy_recipient_repository import (
        SQLAlchemyRecipientRepository,
    )

    recipient = make_recipient(timezone="Europe/Lisbon", language="pt")

    model = SQLAlchemyRecipientRepository._to_model(recipient)
    assert model.timezone == "Europe/Lisbon"
    assert model.language == "pt"

    rehydrated = SQLAlchemyRecipientRepository._to_entity(model)
    assert rehydrated.timezone == "Europe/Lisbon"
    assert rehydrated.language == "pt"
    assert rehydrated.id == recipient.id


def test_model_columns_exist_with_nullable_facts():
    """The persistence model has the profile columns, nullable for unknown."""
    from tiber.infrastructure.models.recipient import RecipientModel

    assert RecipientModel.__table__.c.timezone.nullable is True
    assert RecipientModel.__table__.c.language.nullable is True
