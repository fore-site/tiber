from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from ...domain.entities import Notification
from ...domain.value_objects import (
    ContentAction,
    ContentImage,
    NotificationContent,
)

ChannelName = Literal["email", "sms", "push", "in_app"]
_ADDRESS_FIELDS = ("email", "sms", "push", "in_app")
Category = Literal["critical", "informational", "social", "promotional"]
NotificationStatus = Literal[
    "pending",
    "processing",
    "delivered",
    "failed",  # Internal, network, or provider outages
    "bounced",  # Recipient-side rejection
    "suppressed",  # System-level intentional drops
    "postponed",
    "cancelled",
]


def _client_key(stored: str | None, channel: str) -> str | None:
    """Strip the per-channel suffix so clients see the key they sent."""
    if stored is None:
        return None
    suffix = f":{channel}"
    return stored.removesuffix(suffix)


def mask_address(channel: str, address: str | None) -> str | None:
    """Mask email address and phone number details."""
    if not address:
        return None
    if channel == "email":
        local, _, domain = address.partition("@")
        return f"{local[:1]}***@{domain}"
    elif channel == "sms":
        return f"{address[:2]}***{address[-2:]}" if len(address) > 6 else "***"
    return None


class ContentActionModel(BaseModel):
    """One recipient action (e.g. a button) on the API wire."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    label: str = Field(
        min_length=1,
        description="Button/link text; escaped as text on render.",
    )

    url: str = Field(
        description="Absolute http(s) URL the action points to.",
    )


class ContentImageModel(BaseModel):
    """One embedded image on the API wire."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    url: str = Field(
        description="Absolute http(s) URL of the image.",
    )

    alt: str | None = Field(
        default=None,
        description="Accessibility text; recipients may block remote images.",
    )


class NotificationContentModel(BaseModel):
    """Channel-agnostic notification content on the API wire.

    Mirrors the domain ``NotificationContent`` value object: the API exposes
    meaning (title, body, actions, images), never channel-specific bytes.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: str | None = Field(
        default=None,
        max_length=255,
        description="Message title; used by channels that support one (e.g. email subject).",
    )

    body: str = Field(
        min_length=1,
        description="Message body text.",
    )

    actions: list[ContentActionModel] = Field(
        default_factory=list,
        description="Ordered recipient actions (e.g. buttons); interpreted per channel.",
    )

    images: list[ContentImageModel] = Field(
        default_factory=list,
        description="Embedded images; interpreted per channel.",
    )

    def to_domain(self) -> NotificationContent:
        """Convert the wire content into the domain value object."""
        return NotificationContent(
            title=self.title,
            body=self.body,
            actions=tuple(
                ContentAction(label=a.label, url=a.url) for a in self.actions
            ),
            images=tuple(ContentImage(url=i.url, alt=i.alt) for i in self.images),
        )


class NotificationCreateRequest(BaseModel):
    """Request payload for creating a notification."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    recipient_id: str | None = Field(
        default=None,
        description="Client's own recipient identifier for the selected channel.",
    )

    channels: list[ChannelName] | None = Field(
        default=None,
        description=(
            "Restrict delivery to these channels. Only valid with ``recipient_id``. "
            "Omit to let the ML ranker choose among the recipient's registered channels. "
            "Every listed channel must have a registered address. "
            "All listed channels are delivered in parallel; list order carries no priority. "
        ),
    )

    email: EmailStr | None = None
    sms: str | None = Field(default=None, min_length=1)
    push: str | None = Field(default=None, min_length=1)
    in_app: str | None = Field(default=None, min_length=1)

    category: Category | None = Field(
        default=None,
        description="Delivery category; drives policy treatment (e.g. CRITICAL bypasses quiet hours).",
    )

    group_key: str | None = None

    topic_slug: str | None = None

    template_slug: str | None = None

    template_variables: dict[str, Any] | None = Field(
        default=None,
        description="Variables substituted into the template when `template_slug` is set.",
    )

    content: NotificationContentModel | None = Field(
        default=None,
        description="Direct content; required when `template_slug` is not set.",
    )

    send_at: datetime | None = Field(
        default=None,
        description=(
            "Optional ISO-8601 timestamp for when the notification should be "
            "sent. When omitted, the notification is sent immediately."
        ),
    )

    idempotency_key: str | None = None

    @property
    def adhoc_channels(self) -> set[str]:
        """Get a set of client-provided addresses."""
        return {c for c in _ADDRESS_FIELDS if getattr(self, c) is not None}

    def address_map(self) -> dict[ChannelName, str]:
        """Supplied addresses keyed by channel name (route maps to DeliveryChannel)."""
        return {
            c: getattr(self, c) for c in _ADDRESS_FIELDS if getattr(self, c) is not None
        }

    @model_validator(mode="after")
    def _validate_request(self) -> Self:
        adhoc = self.adhoc_channels

        if self.recipient_id and adhoc:
            raise ValueError(
                "Provide either `recipient_id` or channel addresses, not both."
            )
        if not self.recipient_id and not adhoc:
            raise ValueError("Provide `recipient_id` or at least one channel address.")

        # Channel selection (registered recipients only)
        if self.channels is not None:
            if not self.recipient_id:
                raise ValueError(
                    "`channels` can only be used with `recipient_id`. "
                    "For channel addresses, omit the ones you don't want delivered to."
                )
            if not self.channels:
                raise ValueError("`channels` cannot be empty; omit it instead.")
            if len(set(self.channels)) != len(self.channels):
                raise ValueError("`channels` must not contain duplicates.")

        # Content
        if self.template_slug is None and self.content is None:
            raise ValueError("Provide `content` when `template_slug` is not set.")
        if self.template_variables is not None and self.template_slug is None:
            raise ValueError("`template_variables` requires `template_slug`.")

        # Category
        if self.category == "critical" and self.send_at is not None:
            raise ValueError(
                "`send_at` must not be set for CRITICAL notifications. They are sent immediately."
            )

        # Send_at
        if self.send_at is not None and self.send_at.tzinfo is None:
            raise ValueError("`send_at` must be timezone-aware (UTC or other)")

        return self


class NotificationResponse(BaseModel):
    """A single-channel notification. One is created per resolved channel."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    correlation_id: UUID = Field(
        description="Shared by every notification created from the same request.",
    )

    recipient_id: str | None = None
    channel: ChannelName

    address: str | None = Field(
        default=None,
        description="Masked destination. Only returned for requests that supplied addresses.",
    )

    category: Category
    template_slug: str | None = None
    topic_slug: str | None = None
    group_key: str | None = None
    content: NotificationContentModel = Field(
        description="Content delivered on this channel (rendered from the template, or supplied directly).",
    )

    status: NotificationStatus
    send_at: datetime | None = None
    send_time_basis: Literal["immediate", "explicit", "ml_predicted"]
    delivered_at: datetime | None = None

    idempotency_key: str | None = Field(
        default=None,
        description="The key supplied in the request, shared by all notifications in the batch.",
    )

    suppression_reason: str | None = None
    cancellation_reason: str | None = None
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(
        cls,
        n: Notification,
        *,
        address: str | None = None,
        recipient_id: str | None = None,
        template_slug: str | None = None,
        topic_slug: str | None = None,
    ) -> NotificationResponse:
        """Build DTO response from domain entity."""
        return cls(
            id=n.id,
            project_id=n.project_id,
            correlation_id=n.correlation_id,
            recipient_id=recipient_id,
            channel=n.channel.value,
            address=mask_address(n.channel.value, address),
            category=n.category.value,
            template_slug=template_slug,
            topic_slug=topic_slug,
            group_key=n.group_key,
            content=NotificationContentModel(**n.content.to_dict()),
            status=n.status.value,
            send_at=n.send_at,
            send_time_basis=n.send_time_basis.value
            if n.send_time_basis
            else "immediate",
            delivered_at=n.delivered_at,
            idempotency_key=_client_key(n.idempotency_key, n.channel),
            suppression_reason=n.suppression_reason,
            cancellation_reason=n.cancellation_reason,
            failure_reason=n.failure_reason,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )


class NotificationBatchResponse(BaseModel):
    """Result of a create request: one notification per resolved channel."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: UUID
    notifications: list[NotificationResponse]

    @classmethod
    def from_entities(
        cls,
        correlation_id: UUID,
        notifications: Sequence[Notification],
        *,
        address: str | None,
        recipient_id: str | None,
        template_slugs: Mapping[UUID, str],
        topic_slugs: Mapping[UUID, str],
    ) -> NotificationBatchResponse:
        """Build response from domain entity."""
        return cls(
            correlation_id=correlation_id,
            notifications=[
                NotificationResponse.from_entity(
                    n,
                    address=address,
                    recipient_id=recipient_id,
                    template_slug=template_slugs.get(n.template_id)
                    if n.template_id is not None
                    else None,
                    topic_slug=topic_slugs.get(n.topic_id)
                    if n.topic_id is not None
                    else None,
                )
                for n in notifications
            ],
        )
