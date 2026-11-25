"""Recipient consent state: schema validation, persistence, response shape."""

from __future__ import annotations

from datetime import UTC, datetime, time
from types import TracebackType
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from tiber.api.schemas.recipient import (
    RecipientCreateRequest,
    RecipientPreferencesRequest,
    RecipientResponse,
)
from tiber.application.services.recipient_management import (
    RecipientManagementService,
)
from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.exceptions import InvalidEntityAttributeError
from tiber.domain.value_objects import (
    BlackoutPeriod,
    QuietHours,
    RecipientPreferences,
)
from tiber.domain.value_objects.preferences import UNSET
from tiber.infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)


def time_preferences() -> tuple[BlackoutPeriod, QuietHours]:
    """Build one blackout and one quiet-hours window for a recipient."""
    return (
        BlackoutPeriod(
            name="holiday",
            start=datetime(2026, 12, 24, tzinfo=UTC),
            end=datetime(2026, 12, 26, tzinfo=UTC),
        ),
        QuietHours(
            name="night",
            window_start=time(22, 0),
            window_end=time(6, 0),
            channel=DeliveryChannel.EMAIL,
            description="Do not email overnight",
        ),
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


def test_time_preferences_survive_a_persistence_round_trip():
    """Recipient-level blackouts and quiet hours are stored, not dropped."""
    blackout, quiet = time_preferences()
    preferences = RecipientPreferences(
        blackout_period=blackout,
        quiet_hours=quiet,
    )

    model = SQLAlchemyRecipientRepository._to_model(make_recipient(preferences))
    restored = SQLAlchemyRecipientRepository._to_entity(model)

    assert model.preferences["blackout_period"] == {
        "name": "holiday",
        "start": "2026-12-24T00:00:00+00:00",
        "end": "2026-12-26T00:00:00+00:00",
    }
    assert restored.preferences == preferences


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
    assert payload.blackout_period_update() is UNSET
    assert payload.quiet_hours_update() is UNSET


def test_explicit_null_clears_a_time_preference():
    """JSON null is a clear instruction, distinct from an omitted field."""
    payload = RecipientPreferencesRequest.model_validate(
        {"blackout_period": None, "quiet_hours": None}
    )

    assert payload.blackout_period_update() is None
    assert payload.quiet_hours_update() is None


def test_time_preferences_are_validated_by_the_domain_value_objects():
    """An inverted blackout never reaches persistence through the API."""
    with pytest.raises(ValidationError, match="cannot be after end"):
        RecipientPreferencesRequest.model_validate(
            {
                "blackout_period": {
                    "name": "inverted",
                    "start": "2026-12-26T00:00:00Z",
                    "end": "2026-12-24T00:00:00Z",
                }
            }
        )


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
    """The value object refuses to store a CRITICAL unsubscribe."""
    with pytest.raises(ValueError, match="CRITICAL"):
        RecipientPreferences().merged_with(unsubscribed_categories=["critical"])


def test_merge_leaves_omitted_time_preferences_untouched():
    """Not mentioning a time restriction is not a request to clear it."""
    blackout, quiet = time_preferences()
    current = RecipientPreferences(blackout_period=blackout, quiet_hours=quiet)

    merged = current.merged_with(opted_out_channels=[DeliveryChannel.EMAIL])

    assert merged.blackout_period == blackout
    assert merged.quiet_hours == quiet


def test_merge_can_clear_and_replace_time_preferences():
    """None clears; an object replaces the stored time restriction."""
    blackout, quiet = time_preferences()
    replacement = BlackoutPeriod(
        name="maintenance",
        start=datetime(2027, 1, 1, tzinfo=UTC),
        end=datetime(2027, 1, 2, tzinfo=UTC),
    )
    current = RecipientPreferences(blackout_period=blackout, quiet_hours=quiet)

    cleared = current.merged_with(blackout_period=None)
    replaced = cleared.merged_with(blackout_period=replacement)

    assert cleared.blackout_period is None
    assert cleared.quiet_hours == quiet
    assert replaced.blackout_period == replacement


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


def test_response_exposes_recipient_time_restrictions():
    """A stored blackout and quiet window round-trip through the response."""
    blackout, quiet = time_preferences()
    payload = RecipientResponse.from_entity(
        make_recipient(
            RecipientPreferences(blackout_period=blackout, quiet_hours=quiet)
        )
    )

    assert payload.blackout_period is not None
    assert payload.blackout_period.name == "holiday"
    assert payload.quiet_hours is not None
    assert payload.quiet_hours.window_start == time(22, 0)
    assert payload.quiet_hours.channel is DeliveryChannel.EMAIL


# --- Service ---


class _NullUnitOfWork:
    """Stand in for the transaction boundary; rejection happens before it opens."""

    async def __aenter__(self) -> _NullUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class _RecipientRepository:
    """Resolve one stored recipient by external id."""

    def __init__(self, recipient: Recipient) -> None:
        self._recipient = recipient

    async def get_by_external_id(self, external_id: str, project_id: UUID) -> Recipient:
        """Return the stored recipient regardless of the lookup keys."""
        return self._recipient


async def test_update_rejects_a_critical_unsubscribe():
    """CRITICAL is unstorable, so the service surfaces the domain rejection."""
    service = RecipientManagementService(
        unit_of_work=_NullUnitOfWork(),
        recipient_repository=_RecipientRepository(make_recipient()),
    )

    with pytest.raises(InvalidEntityAttributeError, match="CRITICAL"):
        await service.update_preferences_by_external_id(
            project_id=uuid4(),
            external_id="user-1",
            unsubscribed_categories=[NotificationCategory.CRITICAL],
        )
