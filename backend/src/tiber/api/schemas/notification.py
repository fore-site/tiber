from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...domain.entities import Notification


class NotificationCreateRequest(BaseModel):
    """Request payload for creating a notification."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    recipient_id: UUID = Field(
        description="Recipient identifier for the selected channel.",
    )

    channel: Literal[
        "email",
        "sms",
        "push",
        "webhook",
        "in_app",
    ]

    template_id: UUID | None = None

    subject: str | None = Field(
        default=None,
        max_length=255,
    )

    body: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    scheduled_at: datetime | None = Field(
        default=None,
        description=(
            "Optional ISO-8601 timestamp for when the notification should be "
            "sent. When omitted, the notification is sent immediately."
        ),
    )


class NotificationResponse(BaseModel):
    """Response payload for a notification."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    id: UUID
    project_id: UUID
    recipient_id: UUID
    template_id: UUID | None = None
    channel: str
    status: str
    content: dict[str, Any]
    idempotency_key: str
    correlation_id: UUID
    scheduled_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, notification: Notification) -> NotificationResponse:
        """Build a response DTO from a domain entity."""
        return cls(
            id=notification.id,
            project_id=notification.project_id,
            recipient_id=notification.recipient_id,
            template_id=notification.template_id,
            channel=notification.channel.value,
            status=notification.status.value,
            content={
                "subject": notification.content.subject,
                "body": notification.content.body,
            },
            idempotency_key=notification.idempotency_key or "",
            correlation_id=notification.correlation_id,
            scheduled_at=notification.scheduled_at,
            delivered_at=notification.delivered_at,
            created_at=notification.created_at,
            updated_at=notification.updated_at,
        )
