"""Maps the validated HTTP request onto the application command."""

from __future__ import annotations

from uuid import UUID

from tiber.api.schemas.notification import NotificationCreateRequest
from tiber.application.services.notification_intake import AcceptNotificationCommand


def to_accept_command(
    request: NotificationCreateRequest,
    *,
    project_id: UUID,
    idempotency_key: str,
) -> AcceptNotificationCommand:
    """Map from NotificationCreateRequest to AcceptNotificationCommand."""
    return AcceptNotificationCommand(
        project_id=project_id,
        recipient_id=request.recipient_id,
        addresses=request.address_map(),  # already keyed by DeliveryChannel
        channels=request.channels,  # list[DeliveryChannel] | None
        category=request.category,  # None is meaningful: the ML infers it
        topic_slug=request.topic_slug,  # None is meaningful: the ML infers it
        template_slug=request.template_slug,
        template_variables=request.template_variables,
        content=request.content.to_domain() if request.content is not None else None,
        group_key=request.group_key,
        send_at=request.send_at,
        idempotency_key=idempotency_key,
    )
