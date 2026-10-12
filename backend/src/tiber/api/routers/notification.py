from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from ...application.services import NotificationService
from ...core.logging import get_correlation_id
from ...infrastructure.models import ProjectModel
from ...infrastructure.rate_limit.ingestion_rate_limiter import IngestionRateLimiter
from ..dependencies import (
    get_authenticated_project,
    get_ingestion_rate_limiter,
    get_notification_service,
)
from ..schemas.notification import (
    NotificationCreateRequest,
    NotificationCreateResponse,
    NotificationResponse,
)

router = APIRouter()


@router.post(
    "/projects/{project_id}/notifications",
    response_model=NotificationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_notification(
    payload: NotificationCreateRequest,
    project: Annotated[
        ProjectModel,
        Depends(get_authenticated_project),
    ],
    service: Annotated[
        NotificationService,
        Depends(get_notification_service),
    ],
    limiter: Annotated[
        IngestionRateLimiter,
        Depends(get_ingestion_rate_limiter),
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key"),
    ],
    correlation_id: Annotated[
        str | None,
        Depends(get_correlation_id),
    ],
) -> NotificationCreateResponse:
    """Create a notification.

    Requires an ``Idempotency-Key`` header. A repeated submission with the
    same key within 24h returns the originally persisted notification.

    Ingestion is rate-limited per project: once the project's windowed quota is
    exhausted the request is rejected with ``429 Too Many Requests``.
    """
    if not await limiter.is_allowed(project.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Ingestion rate limit exceeded.",
        )
    cid = UUID(correlation_id) if correlation_id else uuid4()
    await service.create_notification(
        project_id=project.id,
        recipient_id=payload.recipient_id,
        category=payload.category,
        topic_slug=payload.topic_slug,
        channels=payload.channels,
        addresses=payload.address_map(),
        content=payload.content.to_domain() if payload.content is not None else None,
        template_slug=payload.template_slug,
        template_variables=payload.template_variables,
        idempotency_key=idempotency_key,
        group_key=payload.group_key,
        correlation_id=cid,
        send_at=payload.send_at,
    )
    return NotificationCreateResponse.from_input(project.id, cid)


@router.get(
    "/projects/{project_id}/notifications/{notification_id}",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
)
async def get_notification(
    project: Annotated[
        ProjectModel,
        Depends(get_authenticated_project),
    ],
    notification_id: UUID,
    service: Annotated[
        NotificationService,
        Depends(get_notification_service),
    ],
) -> NotificationResponse:
    """Retrieve a notification by its ID."""
    notification = await service.get_notification(project.id, notification_id)
    return NotificationResponse.from_entity(notification)


@router.get(
    "/projects/{project_id}/notifications",
    response_model=list[NotificationResponse],
    status_code=status.HTTP_200_OK,
)
async def list_notifications(
    project: Annotated[
        ProjectModel,
        Depends(get_authenticated_project),
    ],
    service: Annotated[
        NotificationService,
        Depends(get_notification_service),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NotificationResponse]:
    """List notifications for a project (most recent first is not yet ordered)."""
    notifications = await service.list_notifications(project.id, limit, offset)
    return [NotificationResponse.from_entity(n) for n in notifications]


@router.put(
    "/projects/{project_id}/notifications/{notification_id}/cancellation",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_notification(
    project: Annotated[
        ProjectModel,
        Depends(get_authenticated_project),
    ],
    notification_id: UUID,
) -> None:
    """Cancel a scheduled notification.

    Requires repository update semantics via the immutable entity transition;
    TODO: wire ``Notification.mark_cancelled()`` through the repository.
    """
    raise NotImplementedError
