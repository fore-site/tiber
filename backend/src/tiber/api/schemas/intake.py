"""Response schemas for reading an intake back.

POST /notifications                      -> 202 ``NotificationCreateResponse`` (notification.py)
GET  /notifications?correlation_id=...   -> ``IntakeStatusResponse``
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...domain.entities import Notification, Recipient
from ...domain.entities.notification_intake import NotificationIntake
from ...domain.enums import IntakeStatus, NotificationCategory
from ...domain.value_objects.intake import ChannelSource, DecisionSource
from .notification import NotificationResponse

# Internal failure detail (exception text) is never returned to clients.
_PUBLIC_FAILURE_MESSAGE = "Processing failed. Contact support with the correlation_id."


class DecisionSummary(BaseModel):
    """What was decided for the fields the client left open, and where each came from."""

    model_config = ConfigDict(extra="forbid")

    category: NotificationCategory
    category_source: DecisionSource
    topic_slug: str | None = None
    topic_source: DecisionSource | None = None
    channel_source: ChannelSource
    model_version: str | None = None


class IntakeStatusResponse(BaseModel):
    """Status of the notification intake."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: UUID
    project_id: UUID
    status: IntakeStatus
    failure_reason: str | None = Field(
        default=None,
        description="Set only when processing failed. Quote the correlation_id to support.",
    )
    decisions: DecisionSummary | None = Field(
        default=None,
        description="Present once the intake has been processed.",
    )
    notifications: list[NotificationResponse] = Field(
        default_factory=list,
        description="Empty until processing completes.",
    )

    @classmethod
    def from_intake(
        cls,
        intake: NotificationIntake,
        notifications: Sequence[Notification],
        recipient: Recipient,
    ) -> IntakeStatusResponse:
        """Build the IntakeStatusResponse."""
        plan = intake.plan
        payload = intake.payload
        topic = (plan.topic if plan is not None else None) or payload.topic

        # Addresses are echoed (masked by ``NotificationResponse``) only for requests
        # that supplied them. Registered recipients already know their own addresses.
        expose_addresses = intake.constraints.channel_mode == "addresses"

        return cls(
            correlation_id=intake.correlation_id,
            project_id=intake.project_id,
            status=intake.status,
            failure_reason=intake.failure_reason,
            decisions=(
                DecisionSummary(
                    category=plan.category,
                    category_source=plan.category_source,
                    topic_slug=plan.topic.slug if plan.topic is not None else None,
                    topic_source=plan.topic_source,
                    channel_source=plan.channel_source,
                    model_version=plan.model_version,
                )
                if plan is not None
                else None
            ),
            notifications=[
                NotificationResponse.from_entity(
                    n,
                    # Each child has its own channel, so each gets its own address.
                    address=recipient.addresses.get(n.channel)
                    if expose_addresses
                    else None,
                    recipient_id=recipient.external_id,
                    template_slug=(
                        payload.template_slug
                        if n.template_id is not None
                        and n.template_id == payload.template_id
                        else None
                    ),
                    topic_slug=(
                        topic.slug
                        if topic is not None and n.topic_id == topic.id
                        else None
                    ),
                )
                for n in notifications
            ],
        )
