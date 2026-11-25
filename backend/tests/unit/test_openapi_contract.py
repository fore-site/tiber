"""Guards for the curated OpenAPI document against the API it describes.

The spec is hand-maintained, so these assertions pin the parts that drift
silently: how a recipient is addressed, and what a notification request and
response actually contain.
"""

from pathlib import Path
from typing import Any

import yaml

_SPEC = yaml.safe_load(
    (Path(__file__).parents[2] / "src/tiber/api/openapi.yaml").read_text()
)
_PATHS: dict[str, Any] = _SPEC["paths"]
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_COMPONENT_PARAMS: dict[str, Any] = _SPEC["components"]["parameters"]


def _params(operation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Named parameters of an operation, resolving component references."""
    parameters: dict[str, dict[str, Any]] = {}
    for parameter in operation.get("parameters", []):
        if "$ref" in parameter:
            name = parameter["$ref"].rsplit("/", 1)[-1]
            parameter = _COMPONENT_PARAMS[name]
        parameters[parameter["name"]] = parameter
    return parameters


def test_recipients_are_addressed_by_query_parameter() -> None:
    """Recipient CRUD targets an external id, not a UUID in the path."""
    collection = _PATHS["/v1/projects/{project_id}/recipients"]

    for method in ("patch", "delete"):
        assert _params(collection[method])["recipient"]["in"] == "query"
    assert "permanent" not in _params(collection["delete"])
    assert "/v1/projects/{project_id}/recipients/{recipient_id}" not in _PATHS


def test_recipient_delete_is_a_deactivation_with_no_conflict() -> None:
    """Deleted recipients are never returned, and deactivation cannot conflict."""
    assert "deleted_at" not in _SCHEMAS["Recipient"]["properties"]
    delete = _PATHS["/v1/projects/{project_id}/recipients"]["delete"]
    assert "409" not in delete["responses"]


def test_recipient_list_filters_by_external_id() -> None:
    """The list endpoint filters on the client's identifier, not a UUID."""
    params = _params(_PATHS["/v1/projects/{project_id}/recipients"]["get"])
    assert params["recipient"]["in"] == "query"


def test_create_recipient_requires_only_the_external_id() -> None:
    """An external-ID-only recipient is valid, so addresses cannot be required."""
    schema = _SCHEMAS["CreateRecipientRequest"]

    assert schema["required"] == ["external_id"]
    assert "addresses" in schema["properties"]
    assert "minProperties" not in _SCHEMAS["RecipientAddresses"]
    assert "sms" not in _SCHEMAS["RecipientAddresses"]["properties"]


def test_create_notification_uses_recipient_and_no_flat_sms() -> None:
    """The send payload names the recipient and has no per-channel sms field."""
    properties = _SCHEMAS["CreateNotificationRequest"]["properties"]

    assert "recipient" in properties
    assert "recipient_id" not in properties
    assert "sms" not in properties
    assert properties["channels"]["minItems"] == 1


def test_notification_response_exposes_external_id_not_internal_uuid() -> None:
    """Responses identify the recipient the way the client does."""
    properties = _SCHEMAS["Notification"]["properties"]

    assert "recipient" in properties
    assert "recipient_id" not in properties


def test_engagement_event_attribution_is_nullable_after_erasure() -> None:
    """An event outlives its recipient, so its `recipient_id` may be null."""
    recipient_id = _SCHEMAS["EngagementEvent"]["properties"]["recipient_id"]

    assert recipient_id["nullable"] is True
    assert "erased" in recipient_id["description"].lower()


def test_notification_response_explains_a_missing_recipient() -> None:
    """A null recipient has two causes, and the spec must name both."""
    description = _SCHEMAS["Notification"]["properties"]["recipient"]["description"]

    assert "deleted" in description
    assert "external id" in description


def test_notification_list_declares_its_filters() -> None:
    """The router filters by recipient, channel and status; the spec must say so."""
    params = _params(_PATHS["/v1/projects/{project_id}/notifications"]["get"])
    assert {"recipient", "channel", "status"} <= set(params)


def test_decision_summary_only_reports_client_channel_provenance() -> None:
    """Channels come from the client, so the spec offers no ML provenance."""
    enum = _SCHEMAS["DecisionSummary"]["properties"]["channel_source"]["enum"]
    assert set(enum) == {"client", "addresses"}


def test_recipient_preferences_expose_time_restrictions() -> None:
    """Recipient blackout and quiet-hours configuration is part of the contract."""
    properties = _SCHEMAS["RecipientPreferencesRequest"]["properties"]
    recipient = _SCHEMAS["Recipient"]["properties"]

    assert {"blackout_period", "quiet_hours"} <= set(properties)
    assert {"blackout_period", "quiet_hours"} <= set(recipient)
    assert {"blackout_period", "quiet_hours"} <= set(_SCHEMAS["Recipient"]["required"])


def test_recipient_timezone_is_accepted_and_echoed() -> None:
    """The profile fact quiet hours depend on is settable through the API."""
    recipient = _SCHEMAS["Recipient"]

    assert "timezone" in recipient["required"]
    assert "timezone" in _SCHEMAS["CreateRecipientRequest"]["properties"]
    assert "timezone" in _SCHEMAS["UpdateRecipientRequest"]["properties"]


def test_language_is_not_part_of_the_contract() -> None:
    """The removed profile fact must not linger in any schema."""
    for schema in _SCHEMAS.values():
        assert "language" not in schema.get("properties", {}), schema


def test_delivery_constraint_is_a_project_singleton() -> None:
    """Project constraints are read and replaced at one resource path."""
    path = _PATHS["/v1/projects/{project_id}/delivery-constraint"]

    assert {"get", "put"} <= set(path)
    assert set(_SCHEMAS["DeliveryConstraintUpdateRequest"]["required"]) == {"timezone"}
    assert {"blackout_periods", "quiet_hours"} <= set(
        _SCHEMAS["DeliveryConstraint"]["properties"]
    )
