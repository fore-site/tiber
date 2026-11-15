from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from ...domain.entities import WebhookEndpoint
from ...domain.enums import WebhookEventType


def _unique_events(events: list[WebhookEventType]) -> list[WebhookEventType]:
    """Return the subscription list, rejecting duplicates."""
    if len(set(events)) != len(events):
        raise ValueError("`events` must not contain duplicates.")
    return events


class WebhookEndpointCreateRequest(BaseModel):
    """Fields accepted when registering a webhook endpoint."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: HttpUrl = Field(
        description=(
            "Absolute HTTPS URL on port 443 that resolves only to public "
            "internet addresses. Tiber rejects localhost, private, link-local, "
            "and metadata destinations."
        )
    )
    events: list[WebhookEventType] = Field(
        min_length=1,
        description="Lifecycle events this endpoint subscribes to.",
    )

    @field_validator("events")
    @classmethod
    def _no_duplicate_events(
        cls, events: list[WebhookEventType]
    ) -> list[WebhookEventType]:
        """Reject duplicate subscriptions instead of collapsing them silently."""
        return _unique_events(events)


class WebhookEndpointUpdateRequest(BaseModel):
    """Fields accepted when updating a webhook endpoint."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: HttpUrl | None = Field(
        default=None,
        description=(
            "Replacement HTTPS callback URL on port 443 that resolves only to "
            "public internet addresses."
        ),
    )
    events: list[WebhookEventType] | None = Field(
        default=None,
        min_length=1,
        description="Replacement subscription list.",
    )

    @field_validator("events")
    @classmethod
    def _no_duplicate_events(
        cls, events: list[WebhookEventType] | None
    ) -> list[WebhookEventType] | None:
        """Reject duplicate subscriptions instead of collapsing them silently."""
        return _unique_events(events) if events is not None else None

    @model_validator(mode="after")
    def _require_change(self) -> Self:
        """Reject an update that changes nothing."""
        if self.url is None and self.events is None:
            raise ValueError("Provide `url` or `events`.")
        return self


class WebhookEndpointResponse(BaseModel):
    """API representation of a registered endpoint.

    The signing secret is never included: only its prefix is stored in
    readable form.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    url: str
    events: list[WebhookEventType]
    secret_prefix: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, endpoint: WebhookEndpoint) -> WebhookEndpointResponse:
        """Build the API representation from a domain endpoint."""
        return cls(
            id=endpoint.id,
            project_id=endpoint.project_id,
            url=endpoint.url,
            events=endpoint.events,
            secret_prefix=endpoint.secret_prefix,
            created_at=endpoint.created_at,
            updated_at=endpoint.updated_at,
        )


class WebhookEndpointIssuedResponse(WebhookEndpointResponse):
    """Registration response; the only time the plaintext secret is returned."""

    model_config = ConfigDict(frozen=True)

    signing_secret: str = Field(
        description="Store this to verify callbacks; it cannot be retrieved again."
    )

    @classmethod
    def from_issued(
        cls, endpoint: WebhookEndpoint, signing_secret: str
    ) -> WebhookEndpointIssuedResponse:
        """Build the registration response from the issued endpoint and secret."""
        base = WebhookEndpointResponse.from_entity(endpoint)
        return cls(**base.model_dump(), signing_secret=signing_secret)


class WebhookEndpointPageResponse(BaseModel):
    """One cursor page of registered webhook endpoints."""

    model_config = ConfigDict(frozen=True)

    data: list[WebhookEndpointResponse]
    next_cursor: str | None = None
