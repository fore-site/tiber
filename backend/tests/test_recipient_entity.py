"""Tests for Recipient static profile facts (doc 08, D1).

``timezone`` and ``language`` are facts about a person, set once by the
client and updated when they change. Pins:

- ``None`` means unknown — no fabricated default (facts, not configuration;
  contrasts with DeliveryConstraint.timezone's UTC default).
- Facts validate on every construction path: create(), reconstitute(),
  direct instantiation, and update_profile() all funnel through
  __post_init__, so an invalid fact is unrepresentable anywhere.
- update_profile() is a full restatement, not a patch: passing None
  withdraws a fact. The copy carries a fresh updated_at.
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


# --- update_profile(): full restatement semantics ---


def test_update_profile_sets_facts():
    """Setting facts bumps updated_at; the frozen original is untouched."""
    recipient = make_recipient()
    before = recipient.updated_at

    updated = recipient.update_profile(timezone="Europe/Lisbon", language="pt")

    assert updated.timezone == "Europe/Lisbon"
    assert updated.language == "pt"
    assert updated.updated_at > before
    # Frozen entity: the original is untouched.
    assert recipient.timezone is None


def test_update_profile_withdraws_a_fact():
    """None is a restatement to unknown, not a no-op patch."""
    recipient = make_recipient(timezone="Europe/Lisbon")

    updated = recipient.update_profile(timezone=None, language="en")

    assert updated.timezone is None
    assert updated.language == "en"


def test_update_profile_rejects_invalid_fact():
    """Validation runs on the mutation path too; failure leaves no trace."""
    recipient = make_recipient(timezone="Europe/Lisbon")

    with pytest.raises(ValueError, match="Invalid timezone"):
        recipient.update_profile(timezone="Bogus/Zone", language="en")

    # The original survives untouched — frozen entity, invalid copy rejected.
    assert recipient.timezone == "Europe/Lisbon"


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
