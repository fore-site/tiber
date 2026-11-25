"""The recipient profile timezone as the API sees it.

Pins the request/response contract for the one profile fact a client can set:

- On registration it is optional, and ``null``/omitted both mean unknown.
- An unresolvable zone is a field-level 422, not an accepted string that only
  fails later during quiet-hours evaluation.
- On update it is partial: omitted keeps, ``null`` withdraws, a value replaces.
- It is echoed back, because clients cannot otherwise tell a stored fact from
  an assumed one.
- ``language`` is not part of the contract: it was removed, and ``extra=forbid``
  makes an old client fail loudly instead of having the field silently dropped.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from tiber.api.v1.schemas.recipient import (
    RecipientCreateRequest,
    RecipientResponse,
    RecipientUpdateRequest,
)
from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel
from tiber.domain.value_objects.preferences import UNSET


def test_registration_defaults_the_timezone_to_unknown():
    """Omitted means unknown; the API does not invent UTC."""
    payload = RecipientCreateRequest(external_id="user-1")

    assert payload.timezone is None


def test_registration_accepts_an_iana_timezone():
    """A valid zone is carried through as given."""
    payload = RecipientCreateRequest(external_id="user-1", timezone="Europe/Lisbon")

    assert payload.timezone == "Europe/Lisbon"


def test_registration_rejects_an_unresolvable_timezone():
    """A zone the runtime cannot resolve is rejected at the edge."""
    with pytest.raises(ValidationError, match="unknown IANA timezone"):
        RecipientCreateRequest(external_id="user-1", timezone="Mars/Olympus_Mons")


def test_language_is_no_longer_accepted():
    """The removed profile fact is unknown to the schema, not ignored."""
    with pytest.raises(ValidationError, match="language"):
        RecipientCreateRequest(external_id="user-1", language="pt-BR")


def test_update_omitting_the_timezone_keeps_it():
    """The address book is required; the fact is not restated by omission."""
    payload = RecipientUpdateRequest(addresses={"email": "jane@example.com"})

    assert payload.timezone_update() is UNSET


def test_update_with_null_timezone_withdraws_it():
    """Explicit null is a statement of unknown, distinguishable from omission."""
    payload = RecipientUpdateRequest(
        addresses={"email": "jane@example.com"}, timezone=None
    )

    assert payload.timezone_update() is None


def test_update_with_a_timezone_replaces_it():
    """A value is a restatement."""
    payload = RecipientUpdateRequest(
        addresses={"email": "jane@example.com"}, timezone="Asia/Tokyo"
    )

    assert payload.timezone_update() == "Asia/Tokyo"


def test_update_rejects_an_unresolvable_timezone():
    """The update path validates as strictly as registration."""
    with pytest.raises(ValidationError, match="unknown IANA timezone"):
        RecipientUpdateRequest(addresses={}, timezone="Not/AZone")


def test_response_echoes_the_stored_timezone():
    """The response reports the fact, including when it is unknown."""
    recipient = Recipient.create(
        project_id=uuid4(),
        external_id="user-1",
        addresses={DeliveryChannel.EMAIL: "jane@example.com"},
        timezone="Europe/Lisbon",
    )
    unknown = Recipient.create(
        project_id=uuid4(),
        external_id="user-2",
        addresses={DeliveryChannel.EMAIL: "john@example.com"},
    )

    payload = RecipientResponse.from_entity(recipient)
    bare = RecipientResponse.from_entity(unknown)

    assert payload.timezone == "Europe/Lisbon"
    assert bare.timezone is None
