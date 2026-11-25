"""Tests for Recipient profile, addresses, and claim lifecycle.

Pins:

- ``timezone`` is a fact about a person: ``None`` means unknown, never a
  fabricated default (contrasts with DeliveryConstraint.timezone's UTC
  default — facts vs configuration).
- The fact validates on every construction path: create(), reconstitute(),
  direct instantiation all funnel through __post_init__, so an invalid
  timezone is unrepresentable anywhere.
- update_timezone() restates the fact, not a patch: passing None withdraws
  it. The copy carries a fresh updated_at.
- update_addresses() and update_preferences() replace their state group;
  update_addresses() enforces the non-empty invariant explicitly.
- claim_addresses() attaches a human identity: merges addresses
  (incoming wins), rejects empty/duplicate claims, stamps updated_at.
- delete() is the doc-less twin of claim(): it hides the row and scrubs the
  personal data (identity, addresses, timezone) in one copy, keeping consent
  state, because the row outlives the person for history's sake.
- The fact survives persistence round-trips (model column <-> entity field).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel
from tiber.domain.exceptions import InvalidEntityAttributeError
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


# --- The fact defaults to unknown, never fabricated ---


def test_profile_timezone_defaults_to_none():
    """A recipient without a stated timezone has an unknown one, not UTC."""
    recipient = make_recipient()

    assert recipient.timezone is None


# --- create() accepts and validates the fact ---


def test_create_with_valid_timezone():
    """A valid IANA zone is stored as given."""
    recipient = make_recipient(timezone="Europe/Lisbon")

    assert recipient.timezone == "Europe/Lisbon"


def test_create_rejects_unknown_timezone():
    """A non-IANA zone raises the same error shape as DeliveryConstraint."""
    with pytest.raises(InvalidEntityAttributeError, match="Invalid timezone"):
        make_recipient(timezone="Mars/Olympus_Mons")


# --- reconstitute() validates too: bad stored facts cannot rehydrate ---


def test_reconstitute_validates_timezone():
    """Bad stored facts cannot rehydrate — rehydration validates, not trusts."""
    with pytest.raises(InvalidEntityAttributeError, match="Invalid timezone"):
        Recipient.reconstitute(
            id=uuid4(),
            project_id=uuid4(),
            addresses={DeliveryChannel.EMAIL: "jane@example.com"},
            preferences=RecipientPreferences(),
            external_id=None,
            timezone="Not/AZone",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            deleted_at=None,
        )


# --- update_timezone(): restatement semantics ---


def test_update_timezone_states_current_truth():
    """Setting the fact bumps updated_at; the frozen original is untouched."""
    recipient = make_recipient()
    before = recipient.updated_at

    updated = recipient.update_timezone("Europe/Lisbon")

    assert updated.timezone == "Europe/Lisbon"
    assert updated.updated_at > before
    # Frozen entity: the original is untouched.
    assert recipient.timezone is None


def test_update_timezone_withdraws_the_fact():
    """None is a restatement to unknown, not a no-op patch."""
    recipient = make_recipient(timezone="Europe/Lisbon")

    updated = recipient.update_timezone(None)

    assert updated.timezone is None


def test_update_timezone_rejects_invalid_fact():
    """Validation runs on the mutation path too; failure leaves no trace."""
    recipient = make_recipient(timezone="Europe/Lisbon")

    with pytest.raises(InvalidEntityAttributeError, match="Invalid timezone"):
        recipient.update_timezone("Bogus/Zone")

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


# --- The fact survives the persistence round-trip ---


def test_timezone_round_trips_through_model_mapping():
    """_to_model carries the fact into the column; _to_entity rehydrates it.

    Uses the repository's static mappers directly — the same code path a
    session save/load exercises — so a column omission shows up here as a
    None rehydrated where a fact was set.
    """
    from tiber.infrastructure.repositories.sqlalchemy_recipient_repository import (
        SQLAlchemyRecipientRepository,
    )

    recipient = make_recipient(timezone="Europe/Lisbon")

    model = SQLAlchemyRecipientRepository._to_model(recipient)
    assert model.timezone == "Europe/Lisbon"

    rehydrated = SQLAlchemyRecipientRepository._to_entity(model)
    assert rehydrated.timezone == "Europe/Lisbon"
    assert rehydrated.id == recipient.id


def test_model_column_exists_nullable_and_language_is_gone():
    """The persistence model has the profile column, and no ``language``."""
    from tiber.infrastructure.models.recipient import RecipientModel

    assert RecipientModel.__table__.c.timezone.nullable is True
    assert "language" not in RecipientModel.__table__.c


# --- delete(): deactivate and scrub in one step ---


def test_delete_scrubs_personal_data_and_keeps_consent():
    """A deleted recipient keeps no personal data but keeps its opt-outs."""
    recipient = make_recipient(
        external_id="user_12345",
        timezone="Europe/Lisbon",
        preferences=RecipientPreferences(unsubscribed_categories=["promotional"]),
    )
    before = recipient.updated_at

    deleted = recipient.delete()

    assert deleted.deleted_at is not None
    assert deleted.external_id is None
    assert deleted.addresses == {}
    assert deleted.timezone is None
    # Consent is the record that this person opted out; it is not personal data.
    assert deleted.preferences.unsubscribed_categories == frozenset({"promotional"})
    assert deleted.updated_at > before
    assert deleted.id == recipient.id
    # Frozen entity: the live original is untouched.
    assert recipient.deleted_at is None
    assert recipient.external_id == "user_12345"


def test_deleted_tombstone_round_trips_through_the_model():
    """A scrubbed row rehydrates: deleted_at exempts it from the identity rule."""
    from tiber.infrastructure.repositories.sqlalchemy_recipient_repository import (
        SQLAlchemyRecipientRepository,
    )

    deleted = make_recipient(external_id="user_12345").delete()

    rehydrated = SQLAlchemyRecipientRepository._to_entity(
        SQLAlchemyRecipientRepository._to_model(deleted)
    )

    assert rehydrated.deleted_at == deleted.deleted_at
    assert rehydrated.external_id is None
    assert rehydrated.addresses == {}
