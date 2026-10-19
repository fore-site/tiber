"""Maps the validated HTTP request onto the application command.

Framework-agnostic: call it from the route handler with the project id from
auth and, if you accept one, the ``Idempotency-Key`` header.

``NotificationCreateRequest`` already uses the domain enums and converts its own
content and addresses, so this mapper only has to pass them through.
"""

from __future__ import annotations

from uuid import UUID

from tiber.api.schemas.notification import NotificationCreateRequest
from tiber.application.services.notification_intake import AcceptNotificationCommand


def to_accept_command(
    request: NotificationCreateRequest,
    *,
    project_id: UUID,
    idempotency_key: str | None = None,
) -> AcceptNotificationCommand:
    """``idempotency_key`` (e.g. from a header) wins over the body field."""
    return AcceptNotificationCommand(
        project_id=project_id,
        recipient_id=request.recipient_id,
        addresses=request.address_map(),  # already keyed by DeliveryChannel
        channels=request.channels,  # list[DeliveryChannel] | None
        category=request.category,  # None is meaningful: the ML infers it
        topic_slug=request.topic_slug,  # None is meaningful: the ML infers it
        template_slug=request.template_slug,
        template_variables=request.template_variables,
        # to_domain() carries title, body, actions and images.
        content=request.content.to_domain() if request.content is not None else None,
        group_key=request.group_key,
        send_at=request.send_at,
        idempotency_key=idempotency_key or request.idempotency_key,
    )
