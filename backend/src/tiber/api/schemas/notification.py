from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from ...domain.entities import Notification
from ...domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    NotificationStatus,
    SendTimeBasis,
)
from ...domain.value_objects import (
    ContentAction,
    ContentImage,
    NotificationContent,
)

_ADDRESS_FIELDS = ("email", "sms", "push", "in_app")

# E.164. Recipient matching compares address strings, so '0803...' and
# '+234803...' must not both be accepted or they become two recipients.
_E164_PATTERN = r"^\+[1-9]\d{6,14}$"


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
        description=(
            "Client's own identifier for a registered recipient. "
            "Omit it when supplying channel addresses instead."
        ),
    )

    channels: list[DeliveryChannel] | None = Field(
        default=None,
        description=(
            "Restrict delivery to these channels. Only valid with ``recipient_id``. "
            "Omit to let the ML ranker choose among the recipient's registered channels. "
            "Every listed channel must have a registered address. "
            "All listed channels are delivered in parallel; list order carries no priority."
        ),
    )

    # Address-based delivery: every address provided is delivered to. To skip a
    # channel, omit its address.
    email: EmailStr | None = None
    sms: str | None = Field(
        default=None,
        pattern=_E164_PATTERN,
        description="Phone number in international E.164 format, e.g. +2348031234567.",
    )
    push: str | None = Field(default=None, min_length=1)
    in_app: str | None = Field(default=None, min_length=1)

    category: NotificationCategory | None = Field(
        default=None,
        description=(
            "Omit only for non-urgent notifications. "
            "If omitted, the category is inferred and the notification is never "
            "treated as critical, so it may be delayed by quiet hours or "
            "send-time optimization."
        ),
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

    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Client-supplied key making retries safe. Reusing a key with a "
            "different request body is rejected."
        ),
    )

    @property
    def adhoc_channels(self) -> set[str]:
        """Get a set of client-provided addresses."""
        return {c for c in _ADDRESS_FIELDS if getattr(self, c) is not None}

    def address_map(self) -> dict[DeliveryChannel, str]:
        """Supplied addresses keyed by channel name (route maps to DeliveryChannel)."""
        return {
            DeliveryChannel(c): getattr(self, c)
            for c in _ADDRESS_FIELDS
            if getattr(self, c) is not None
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
        if self.category is NotificationCategory.CRITICAL and self.send_at is not None:
            raise ValueError(
                "`send_at` must not be set for CRITICAL notifications. They are sent immediately."
            )

        # Send_at
        if self.send_at is not None and self.send_at.tzinfo is None:
            raise ValueError("`send_at` must be timezone-aware (UTC or other)")

        # Group_key
        if self.group_key is not None:
            if not isinstance(self.group_key, str) or not self.group_key.strip():
                raise ValueError("`group_key` must be a non-empty string when provided")
            if len(self.group_key) > 255:
                raise ValueError("`group_key` must be at most 255 characters")

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
    channel: DeliveryChannel

    address: str | None = Field(
        default=None,
        description="Masked destination. Only returned for requests that supplied addresses.",
    )

    category: NotificationCategory
    template_slug: str | None = None
    topic_slug: str | None = None
    group_key: str | None = None
    content: NotificationContentModel = Field(
        description="Content delivered on this channel (rendered from the template, or supplied directly).",
    )

    status: NotificationStatus
    send_at: datetime | None = None
    send_time_basis: SendTimeBasis
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
            channel=n.channel,
            address=mask_address(n.channel.value, address),
            category=n.category,
            template_slug=template_slug,
            topic_slug=topic_slug,
            group_key=n.group_key,
            content=NotificationContentModel(**n.content.to_dict()),
            status=n.status,
            send_at=n.send_at,
            send_time_basis=n.send_time_basis,
            delivered_at=n.delivered_at,
            # Stored unchanged: children of one request share the client's key.
            idempotency_key=n.idempotency_key,
            suppression_reason=n.suppression_reason,
            cancellation_reason=n.cancellation_reason,
            failure_reason=n.failure_reason,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )


class NotificationBatchResponse(BaseModel):
    """Fetch batch notification linked by correlation_id: one notification per resolved channel."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: UUID
    notifications: list[NotificationResponse]

    @classmethod
    def from_entities(
        cls,
        correlation_id: UUID,
        notifications: Sequence[Notification],
        *,
        addresses: Mapping[DeliveryChannel, str] | None,
        recipient_id: str | None,
        template_slugs: Mapping[UUID, str],
        topic_slugs: Mapping[UUID, str],
    ) -> NotificationBatchResponse:
        """Build response from domain entities.

        ``addresses`` maps each channel to its destination, so every child shows
        its own channel's address. Pass ``None`` for registered recipients.
        """
        return cls(
            correlation_id=correlation_id,
            notifications=[
                NotificationResponse.from_entity(
                    n,
                    address=addresses.get(n.channel) if addresses else None,
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


class NotificationCreateResponse(BaseModel):
    """Response of a notification send request."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    correlation_id: UUID

    @classmethod
    def from_input(
        cls, project_id: UUID, correlation_id: UUID
    ) -> NotificationCreateResponse:
        """DTO response from input."""
        return cls(
            project_id=project_id,
            correlation_id=correlation_id,
        )
